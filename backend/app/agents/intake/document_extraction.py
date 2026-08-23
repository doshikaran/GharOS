"""A3 — Document Extraction Agent (spec §15.2, §5.4).

*Responsibility:* extract structured content from a classified document,
applying the schema from the Document-Type Registry (`DocumentTypeSpec.
field_schema`) for the classified type — field-level confidence and
source-region pointers on every field.
*Model tier:* Flash for clean documents; this agent escalates itself to
Pro-tier internally when its own Flash pass reports the input as degraded
(handwriting, low contrast, skew) — see `extract`'s two-pass design.
*Forbidden:* **inferring anything not literally present.** This module
never constructs an `ExtractedField` with `derivation=Derivation.INFERRED`
— extraction and implication are separate agents by design (spec §15.2;
A12 Implication Agent, Phase 4, is the only agent permitted to infer).
Grep this file: `Derivation.INFERRED` does not appear anywhere below,
enforced by `test_document_extraction.py`'s source-inspection test.
*Failure:* a field whose model-reported confidence falls below its
schema's `confidence_floor` is marked `Derivation.AMBIGUOUS` — never
discarded, never silently accepted at face value (spec §15.2 A3's own
Failure clause: "below threshold -> mark ambiguous, retain image,
surface"). The floor comparison happens in this module's own code, not by
trusting the model's self-reported derivation — a below-floor field
surfaces as ambiguous regardless of what the model claims about itself.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.agents import AgentOutput, ModelTier
from contracts.graph_types import AgentId, Derivation, ExtractedField, FieldSchema, NodeId

from ...persistence.errors import MalformedRegion
from ...persistence.region_resolver import parse_region
from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiCallResult, GeminiClient, MediaPart
from .json_utils import parse_json_response, require_bool, require_float, require_list, require_str

AGENT_ID = AgentId("A3")

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ExtractionRequest:
    """One document's extraction request. Exactly one of `text_content` /
    `media` is populated, matching the document's actual shape — a
    text-shaped source (email body, SMS, chat export) never also carries
    image bytes, and vice versa."""

    source_document_id: NodeId
    type_id: str
    field_schema: tuple[FieldSchema, ...]
    text_content: str | None = None
    media: tuple[MediaPart, ...] = ()

    def __post_init__(self) -> None:
        has_text = self.text_content is not None and self.text_content != ""
        has_media = len(self.media) > 0
        if has_text == has_media:
            raise ValueError(
                "ExtractionRequest requires exactly one of text_content or media to be set "
                f"(has_text={has_text}, has_media={has_media})"
            )


@dataclass(frozen=True, slots=True)
class ExtractionRunResult:
    """A3's output for one document. `extracted_fields` never contains a
    field with `derivation=Derivation.INFERRED` (see module docstring)."""

    agent_output: AgentOutput
    extracted_fields: tuple[ExtractedField, ...]
    fields_not_found: tuple[str, ...]
    """Schema field names the model looked for but reports it could not
    find — surfaced for visibility, never silently absorbed."""
    fields_dropped_unknown_name: tuple[str, ...]
    """Field names the model returned that are not part of this type's
    schema — dropped rather than trusted, logged for audit."""
    fields_dropped_invalid_region: tuple[str, ...]
    """Field names the model returned with a `region` that does not parse
    under either supported region-locator convention — dropped rather
    than kept with a fabricated/empty region."""
    degraded_input_observed: bool
    escalated_to_pro: bool


def _field_schema_block(field_schema: tuple[FieldSchema, ...]) -> str:
    lines = []
    for field in field_schema:
        requiredness = "required" if field.required else "optional"
        lines.append(
            f"- `{field.name}` (type: {field.field_type}, {requiredness}, floor: {field.confidence_floor})"
        )
    return "\n".join(lines)


def _region_convention_note(*, is_multimodal: bool) -> str:
    if is_multimodal:
        return (
            'Give `region` as `"page=<n>;bbox=<x0>,<y0>,<x1>,<y1>"` — page is 1-indexed, '
            "bbox coordinates are pixels of the image/page you were shown, e.g. "
            '`"page=1;bbox=10,20,300,400"`.'
        )
    return (
        'Give `region` as `"<start>-<end>"` — a zero-indexed, half-open byte-offset span into '
        'the EXACT text given below, e.g. `"120-340"`. `text[start:end]` must reproduce or '
        "closely contain the value you read."
    )


class DocumentExtractionAgent:
    """A3 Document Extraction Agent. Dependency-injected on a
    `GeminiClient` — schema-driven and generic across all fourteen
    document types (ADR-008): this class never branches on `type_id`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def extract(self, request: ExtractionRequest) -> ExtractionRunResult:
        """Extracts `request.field_schema`'s fields from one document.

        Two-pass tier escalation: the first pass always runs at
        `ModelTier.FLASH`. If that pass reports `degraded_input_observed`
        (handwriting, low contrast, skew, or similarly hard-to-read
        input), a second pass runs at `ModelTier.PRO` and its result is
        used instead — spec §15.2 A3: "Flash for clean, Pro-tier for
        degraded/handwriting," applied automatically rather than
        requiring an external caller to pre-classify document quality.

        Raises:
            ModelResponseMalformed: a model response could not be parsed
                as the expected JSON shape.
        """
        prompt = load_prompt("A3")
        is_multimodal = len(request.media) > 0
        rendered = prompt.text.format(
            type_id=request.type_id,
            field_schema_block=_field_schema_block(request.field_schema),
            source_kind_note=(
                f"The document is attached as {len(request.media)} image/PDF part(s)."
                if is_multimodal
                else "The document is plain text, given verbatim below."
            ),
            source_body="(see attached image/PDF part(s) above the text of this prompt)"
            if is_multimodal
            else (request.text_content or ""),
            region_convention_note=_region_convention_note(is_multimodal=is_multimodal),
        )

        _flash_result, flash_parsed = self._call(rendered, tier=ModelTier.FLASH, media=request.media)
        degraded = require_bool(flash_parsed, "degraded_input_observed", agent_id=AGENT_ID, default=False)

        used_tier = ModelTier.FLASH
        used_prompt_version = prompt.version
        parsed = flash_parsed
        escalated = False
        if degraded:
            logger.info("agents.intake.a3.escalating_to_pro", type_id=request.type_id)
            _pro_result, pro_parsed = self._call(rendered, tier=ModelTier.PRO, media=request.media)
            parsed = pro_parsed
            used_tier = ModelTier.PRO
            escalated = True

        schema_by_name = {field.name: field for field in request.field_schema}
        extracted_fields: list[ExtractedField] = []
        dropped_unknown: list[str] = []
        dropped_bad_region: list[str] = []

        for raw_field in require_list(parsed, "fields", agent_id=AGENT_ID):
            if not isinstance(raw_field, dict):
                continue
            name = require_str(raw_field, "name", agent_id=AGENT_ID)
            schema_field = schema_by_name.get(name)
            if schema_field is None:
                dropped_unknown.append(name)
                logger.warning(
                    "agents.intake.a3.dropped_unknown_field", type_id=request.type_id, field_name=name
                )
                continue

            region_str = require_str(raw_field, "region", agent_id=AGENT_ID)
            try:
                parse_region(region_str)
            except MalformedRegion:
                dropped_bad_region.append(name)
                logger.warning(
                    "agents.intake.a3.dropped_invalid_region",
                    type_id=request.type_id,
                    field_name=name,
                    region=region_str,
                )
                continue

            field_confidence = require_float(raw_field, "confidence", agent_id=AGENT_ID, default=0.0)
            below_floor = field_confidence < schema_field.confidence_floor
            derivation = Derivation.AMBIGUOUS if below_floor else Derivation.EXTRACTED
            extracted_fields.append(
                ExtractedField(
                    name=name,
                    value=raw_field.get("value"),
                    confidence=field_confidence,
                    source_region=region_str,
                    derivation=derivation,
                )
            )

        fields_not_found_raw = require_list(parsed, "fields_not_found", agent_id=AGENT_ID)
        fields_not_found = tuple(str(name) for name in fields_not_found_raw)

        overall_confidence = (
            sum(field.confidence for field in extracted_fields) / len(extracted_fields)
            if extracted_fields
            else 0.0
        )
        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=used_tier,
            prompt_version=used_prompt_version,
            confidence=overall_confidence,
            derivation=Derivation.EXTRACTED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return ExtractionRunResult(
            agent_output=agent_output,
            extracted_fields=tuple(extracted_fields),
            fields_not_found=fields_not_found,
            fields_dropped_unknown_name=tuple(dropped_unknown),
            fields_dropped_invalid_region=tuple(dropped_bad_region),
            degraded_input_observed=degraded,
            escalated_to_pro=escalated,
        )

    def _call(
        self, rendered_prompt: str, *, tier: ModelTier, media: tuple[MediaPart, ...]
    ) -> tuple[GeminiCallResult, dict[str, object]]:
        call_result = self._gemini_client.generate_multimodal(
            agent_id=AGENT_ID, tier=tier, prompt=rendered_prompt, media=media
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        return call_result, parsed


__all__ = ["AGENT_ID", "DocumentExtractionAgent", "ExtractionRequest", "ExtractionRunResult"]
