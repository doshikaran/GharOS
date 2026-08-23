"""A3b — Line-Item Extraction Agent (spec §15.2).

*Responsibility:* specialised sub-extractor for receipts/itemised bills/
statements — per-line description, quantity, unit price, total, tax;
product-category normalisation across merchants (`category_normalization.
normalize_category`, deterministic, not an LLM judgment call).
*Model tier:* Flash for a clean receipt; Pro-tier multimodal specifically
for degraded thermal receipts, via the same self-escalating two-pass
design as A3 (`document_extraction.py`).
*Forbidden:* inferring items not printed; guessing quantities. This
module never constructs a `LineItemExtraction` with
`derivation=Derivation.INFERRED` (grep-verified by
`test_line_item_extraction.py`, same discipline as A3).
*Failure:* partial extraction is acceptable and flagged — `lines_read` vs
`lines_expected_total` makes a "10 of 12 lines read" result visible to
the caller rather than silently presenting a truncated receipt as
complete. A fabricated line (one the model reports but the household
never actually printed) is not an acceptable failure mode; this module
has no mechanism to fabricate a line — every `LineItemExtraction` traces
to one JSON array entry the model returned.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.agents import AgentOutput, ModelTier
from contracts.graph_types import AgentId, Derivation, ExtractedField, NodeId

from ...persistence.errors import MalformedRegion
from ...persistence.region_resolver import parse_region
from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiCallResult, GeminiClient, MediaPart
from .category_normalization import normalize_category
from .json_utils import parse_json_response, require_bool, require_float, require_list, require_str

AGENT_ID = AgentId("A3b")

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class LineItemExtractionRequest:
    source_document_id: NodeId
    text_content: str | None = None
    media: tuple[MediaPart, ...] = ()
    confidence_floor: float = 0.70
    """Matches the receipt `DocumentTypeSpec.field_schema`'s `line_items`
    entry's `confidence_floor` — passed in rather than hardcoded so this
    agent stays reusable for any type whose schema declares a line-item
    list field (bank/card statements, quotes) with its own floor."""

    def __post_init__(self) -> None:
        has_text = self.text_content is not None and self.text_content != ""
        has_media = len(self.media) > 0
        if has_text == has_media:
            raise ValueError(
                "LineItemExtractionRequest requires exactly one of text_content or media to be set "
                f"(has_text={has_text}, has_media={has_media})"
            )


@dataclass(frozen=True, slots=True)
class LineItemExtraction:
    """One purchase line, ready to become a `contracts.graph_types.
    PurchaseItem` once the calling `ExtractionStrategy` attaches full
    `Provenance` and a `ledger_event_id`."""

    description: str
    normalized_category: str | None
    quantity: float | None
    unit_price: float | None
    line_total: float
    tax: float | None
    confidence: float
    source_region: str
    derivation: Derivation


@dataclass(frozen=True, slots=True)
class LineItemExtractionResult:
    agent_output: AgentOutput
    line_items: tuple[LineItemExtraction, ...]
    lines_read: int
    lines_expected_total: int | None
    degraded_input_observed: bool
    escalated_to_pro: bool

    @property
    def is_partial(self) -> bool:
        """True when the model reports fewer lines read than it believes
        the receipt actually has — the honest "10 of 12 lines read"
        signal (module docstring)."""
        return self.lines_expected_total is not None and self.lines_read < self.lines_expected_total


def _region_convention_note(*, is_multimodal: bool) -> str:
    if is_multimodal:
        return (
            'Give `region` as `"page=<n>;bbox=<x0>,<y0>,<x1>,<y1>"` — page is 1-indexed, '
            "bbox coordinates are pixels of the image you were shown."
        )
    return (
        'Give `region` as `"<start>-<end>"` — a zero-indexed, half-open byte-offset span into the '
        "text below."
    )


class LineItemExtractionAgent:
    """A3b Line-Item Extraction Agent. Dependency-injected on a
    `GeminiClient`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def extract(self, request: LineItemExtractionRequest) -> LineItemExtractionResult:
        """Extracts per-line purchase items from one receipt/bill.

        Raises:
            ModelResponseMalformed: a model response could not be parsed
                as the expected JSON shape.
        """
        prompt = load_prompt("A3b")
        is_multimodal = len(request.media) > 0
        rendered = prompt.text.format(
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
        parsed = flash_parsed
        escalated = False
        if degraded:
            logger.info("agents.intake.a3b.escalating_to_pro")
            _pro_result, pro_parsed = self._call(rendered, tier=ModelTier.PRO, media=request.media)
            parsed = pro_parsed
            used_tier = ModelTier.PRO
            escalated = True

        line_items: list[LineItemExtraction] = []
        for raw_line in require_list(parsed, "line_items", agent_id=AGENT_ID):
            if not isinstance(raw_line, dict):
                continue
            region_str = require_str(raw_line, "region", agent_id=AGENT_ID)
            try:
                parse_region(region_str)
            except MalformedRegion:
                logger.warning("agents.intake.a3b.dropped_invalid_region", region=region_str)
                continue

            description = require_str(raw_line, "description", agent_id=AGENT_ID)
            confidence = require_float(raw_line, "confidence", agent_id=AGENT_ID, default=0.0)
            below_floor = confidence < request.confidence_floor
            derivation = Derivation.AMBIGUOUS if below_floor else Derivation.EXTRACTED

            raw_quantity = raw_line.get("quantity")
            raw_unit_price = raw_line.get("unit_price")
            raw_tax = raw_line.get("tax")
            line_items.append(
                LineItemExtraction(
                    description=description,
                    normalized_category=normalize_category(description),
                    quantity=float(raw_quantity) if isinstance(raw_quantity, int | float) else None,
                    unit_price=float(raw_unit_price) if isinstance(raw_unit_price, int | float) else None,
                    line_total=require_float(raw_line, "line_total", agent_id=AGENT_ID, default=0.0),
                    tax=float(raw_tax) if isinstance(raw_tax, int | float) else None,
                    confidence=confidence,
                    source_region=region_str,
                    derivation=derivation,
                )
            )

        raw_expected = parsed.get("lines_expected_total")
        lines_expected_total = int(raw_expected) if isinstance(raw_expected, int | float) else None

        overall_confidence = (
            sum(item.confidence for item in line_items) / len(line_items) if line_items else 0.0
        )
        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=used_tier,
            prompt_version=prompt.version,
            confidence=overall_confidence,
            derivation=Derivation.EXTRACTED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return LineItemExtractionResult(
            agent_output=agent_output,
            line_items=tuple(line_items),
            lines_read=len(line_items),
            lines_expected_total=lines_expected_total,
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


def build_line_items_field(result: LineItemExtractionResult) -> ExtractedField:
    """Packages a `LineItemExtractionResult` into the single `ExtractedField`
    named `"line_items"` that `strategies.receipt_strategy.
    ReceiptExtractionStrategy.map_to_graph` expects — its `.value` is the
    typed `tuple[LineItemExtraction, ...]` itself (not JSON), so each
    line's own per-line confidence/region/derivation survives into the
    strategy layer instead of being collapsed into one blended field.

    The field's own top-level `confidence`/`derivation`/`source_region`
    (required by `ExtractedField`'s shape, but not actually consulted by
    the receipt strategy, which reads each line's own values instead) use
    the run's overall confidence and the first line's region as a
    reasonable summary — callers that need per-line provenance should use
    `result.line_items` directly rather than this field's own summary
    values.
    """
    overall_confidence = result.agent_output.confidence
    first_region = result.line_items[0].source_region if result.line_items else ""
    worst_derivation = (
        Derivation.AMBIGUOUS
        if any(item.derivation is Derivation.AMBIGUOUS for item in result.line_items)
        else Derivation.EXTRACTED
    )
    return ExtractedField(
        name="line_items",
        value=result.line_items,
        confidence=overall_confidence,
        source_region=first_region,
        derivation=worst_derivation,
    )


__all__ = [
    "AGENT_ID",
    "LineItemExtraction",
    "LineItemExtractionAgent",
    "LineItemExtractionRequest",
    "LineItemExtractionResult",
    "build_line_items_field",
]
