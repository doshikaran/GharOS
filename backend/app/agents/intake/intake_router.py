"""A2 — Intake Router (spec §15.2).

*Responsibility:* classify channel and content type; assess relevance.
*Model tier:* Flash only.
*Forbidden:* extraction, implication, action — this agent never reads a
field value out of the document, never derives an obligation, and never
sends/writes anything. It only decides *which* `DocumentTypeSpec` A3
should apply next.
*Failure:* unknown type -> human triage, never silent discard (spec
§5.4.3 rule 4) — enforced here by always calling
`registry_gap_log.record_registry_gap` on an unresolved classification,
never simply returning `None` and moving on.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from contracts.agents import AgentOutput, ModelTier
from contracts.errors import RegistryGap
from contracts.graph_types import AgentId, Derivation

from ...adapters.document_registry import DocumentTypeRegistry
from ...adapters.ingestion import NormalizedIntake
from ...adapters.registry_gap_log import RegistryGapLog, RegistryGapRecord, record_registry_gap
from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_float, require_list, require_str

AGENT_ID = AgentId("A2")

_UNRESOLVED_CONFIDENCE_FLOOR = 0.35
"""Below this, a classification is treated as unresolved even if the
model named a real registered `type_id` — spec §5.4.3 rule 1:
misclassification is more damaging than low-confidence extraction, so a
low-confidence guess is routed to triage rather than trusted."""


@dataclass(frozen=True, slots=True)
class IntakeRouteResult:
    """A2's output. Exactly one of (`classified_type_id` is set and
    resolved) or (`registry_gap` is set) is true for a fully-processed
    item — `classified_type_id` can also be set with `registry_gap`
    populated when the model named a `type_id` string that turned out not
    to be registered (a defensive path, not the common case)."""

    agent_output: AgentOutput
    classified_type_id: str | None
    type_confidence: float
    runner_up_type_id: str | None
    runner_up_confidence: float
    signals_matched: tuple[str, ...]
    relevance: str
    relevance_reason: str
    registry_gap: RegistryGapRecord | None

    @property
    def resolved(self) -> bool:
        """True only when `classified_type_id` names a real, registered
        type and confidence clears `_UNRESOLVED_CONFIDENCE_FLOOR`."""
        return self.classified_type_id is not None and self.registry_gap is None


def _format_candidate_types_block(registry: DocumentTypeRegistry) -> str:
    lines: list[str] = []
    for type_id in registry.known_type_ids():
        spec, _strategy = registry.resolve(type_id)
        signals = ", ".join(spec.detection_signals)
        lines.append(f"- `{type_id}`: detection signals = [{signals}]")
    return "\n".join(lines)


class IntakeRouter:
    """A2 Intake Router. Dependency-injected on a `GeminiClient`, a
    `DocumentTypeRegistry` (E3-owned, read-only from here), and a
    `RegistryGapLog` (records unknown-type occurrences)."""

    def __init__(
        self,
        *,
        gemini_client: GeminiClient,
        registry: DocumentTypeRegistry,
        gap_log: RegistryGapLog,
    ) -> None:
        self._gemini_client = gemini_client
        self._registry = registry
        self._gap_log = gap_log

    def route(self, intake: NormalizedIntake) -> IntakeRouteResult:
        """Classifies one normalized inbound item against the
        Document-Type Registry's known types.

        Args:
            intake: one channel adapter's normalized output.

        Returns:
            An `IntakeRouteResult`. Never raises on an unresolved
            classification — that path is a normal outcome (registry gap
            recorded, `resolved` is `False`), not an error.

        Raises:
            ModelResponseMalformed: the model's response could not be
                parsed as the expected JSON shape — a genuine plumbing
                failure, distinct from "the model classified this as
                unknown," which is not an error.
        """
        prompt = load_prompt("A2")
        rendered = prompt.text.format(
            candidate_types_block=_format_candidate_types_block(self._registry),
            channel=intake.channel,
            media_type=intake.media_type,
            text_content=intake.text_content or "(no text content — binary/image document)",
        )

        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        raw_type_id = parsed.get("type_id")
        classified_type_id = str(raw_type_id) if isinstance(raw_type_id, str) and raw_type_id else None
        type_confidence = require_float(parsed, "type_confidence", agent_id=AGENT_ID, default=0.0)
        raw_runner_up = parsed.get("runner_up_type_id")
        runner_up_type_id = str(raw_runner_up) if isinstance(raw_runner_up, str) and raw_runner_up else None
        runner_up_confidence = require_float(parsed, "runner_up_confidence", agent_id=AGENT_ID, default=0.0)
        signals_matched = tuple(str(s) for s in require_list(parsed, "signals_matched", agent_id=AGENT_ID))
        relevance = require_str(parsed, "relevance", agent_id=AGENT_ID)
        relevance_reason = require_str(parsed, "relevance_reason", agent_id=AGENT_ID)

        registry_gap: RegistryGapRecord | None = None
        resolved_type_id = classified_type_id
        if classified_type_id is None or type_confidence < _UNRESOLVED_CONFIDENCE_FLOOR:
            gap_error = RegistryGap(
                detection_summary=(
                    f"unresolved classification (type_id={classified_type_id!r}, "
                    f"confidence={type_confidence:.2f}, signals={signals_matched})"
                )
            )
            registry_gap = record_registry_gap(
                self._gap_log,
                gap_error,
                channel=intake.channel,
                type_id_attempted=classified_type_id,
                detection_signals_seen=signals_matched,
                source_document_ref=intake.raw_payload_ref,
            )
            resolved_type_id = None
        elif not self._registry.has_type(classified_type_id):
            gap_error = RegistryGap(
                detection_summary=f"model named unregistered type_id '{classified_type_id}'"
            )
            registry_gap = record_registry_gap(
                self._gap_log,
                gap_error,
                channel=intake.channel,
                type_id_attempted=classified_type_id,
                detection_signals_seen=signals_matched,
                source_document_ref=intake.raw_payload_ref,
            )
            resolved_type_id = None

        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=ModelTier.FLASH,
            prompt_version=prompt.version,
            confidence=type_confidence,
            derivation=Derivation.EXTRACTED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return IntakeRouteResult(
            agent_output=agent_output,
            classified_type_id=resolved_type_id,
            type_confidence=type_confidence,
            runner_up_type_id=runner_up_type_id,
            runner_up_confidence=runner_up_confidence,
            signals_matched=signals_matched,
            relevance=relevance,
            relevance_reason=relevance_reason,
            registry_gap=registry_gap,
        )


__all__ = ["AGENT_ID", "IntakeRouteResult", "IntakeRouter"]
