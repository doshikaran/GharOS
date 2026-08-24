"""A12 — Implication Agent (spec §7.3 Stage 2, §15.4; the flagship agent
of the Consequence Engine, PHASES.md Phase 4).

*Responsibility:* given one SOURCE_DOCUMENT's literal text and the
household's context, derive obligations that are genuinely NOT stated in
the document — the stated/implied split extraction (A3) and implication
(A12) are separate agents by design (gharos-standards skill: merging them
would launder a hallucinated inference as an "extracted" fact).

*Model tier:* Pro-tier, elevated thinking (`_ELEVATED_THINKING_BUDGET_TOKENS`,
opt-in on this agent only — PHASES.md §2.1 rule 4).

*Forbidden:* writing to the graph directly (this module has no
`GraphWriter` import — A15 Obligation Writer is the only writer), acting,
and — the single most safety-critical rule in this phase — **producing an
obligation without a citable span**. This is enforced structurally, not
just by prompt instruction: every candidate's `cited_span_text` is
resolved for real against `request.document_text` by
`citation_validator.locate_and_validate_citation` before an
`ImpliedObligationCandidate` is ever constructed. A model response that
paraphrases instead of quoting, or invents a citation outright, cannot
produce a candidate — it can only produce a `DiscardedInference`, logged,
never surfaced "at low confidence" (spec §7.6).

*Failure:* an uncitable inference is discarded and logged
(`DiscardedInference`), never returned as a low-confidence candidate. A
candidate whose citation IS genuinely resolvable but whose own reported
confidence falls below `_MIN_CANDIDATE_CONFIDENCE` is discarded too, for
the same "never surface as a to-be-distrusted candidate" reason — this is
an additional, stricter floor on top of (not instead of) citation
validity.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

import structlog
from contracts.agents import Citation, ModelTier
from contracts.graph_types import AgentId, Constraint, Obligation, Person

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .citation_validator import locate_and_validate_citation
from .json_utils import optional_int, parse_json_response, require_float, require_list, require_str
from .types import (
    DiscardedInference,
    ImplicationRequest,
    ImplicationRunResult,
    ImpliedObligationCandidate,
)

AGENT_ID = AgentId("A12")

logger = structlog.get_logger(__name__)

_ELEVATED_THINKING_BUDGET_TOKENS = 16_000
"""Opt-in elevated thinking budget for A12 specifically (PHASES.md §2.1
rule 4: "elevated thinking budgets are opt-in per agent, never global").
Deriving obligations that are genuinely NOT stated — reasoning about
capability, lead time, conflicting plans, and coverage needs from a single
paragraph of messy real-world text — is exactly the multi-step, evidence-
weighing reasoning elevated thinking exists for (spec §21.1: "implication
reasoning... Pro-tier, elevated thinking"). No other agent in this package
requests this; any that eventually might sets its own independently-
justified constant, never inherits this one."""

_MIN_CANDIDATE_CONFIDENCE = 0.5
"""Below this, a candidate is discarded even when its citation is
genuinely locatable — safety invariant #4 (low-confidence outputs never
silently proceed) applied to A12's specific output shape, where "proceed"
means "become a graph candidate at all" rather than an action. Distinct
from, and enforced in addition to, `citation_validator.py`'s citation-
validity discard."""


@dataclass(frozen=True, slots=True)
class _RawCandidate:
    """One candidate as the model returned it, before citation validation
    decides whether it may become a real `ImpliedObligationCandidate` or
    only a `DiscardedInference`."""

    label: str
    title: str
    obligation_type: str
    due_at: datetime | None
    effort_estimate_minutes: int | None
    reasoning: str
    cited_span_text: str
    confidence: float
    depends_on_labels: tuple[str, ...]


def _parse_due_at(raw_value: object, *, label: str) -> datetime | None:
    """Best-effort ISO-8601 parse of the model's `due_at` field. A
    malformed (non-ISO) date string is not treated as a fatal parse error
    for the whole response — `due_at` is not the safety-critical field
    here (citation validity is); a candidate with an unparseable due date
    still gets a fair citation-validity/confidence evaluation, just with
    `due_at=None`, logged so the gap is visible rather than silent."""
    if raw_value is None:
        return None
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        return datetime.fromisoformat(raw_value)
    except ValueError:
        logger.warning("agents.consequence.a12.unparseable_due_at", label=label, raw_value=raw_value)
        return None


def _people_block(people: tuple[Person, ...]) -> str:
    if not people:
        return "(no household members recorded yet)"
    lines = []
    for person in people:
        capability_names = [
            name
            for name, has_it in (
                ("can drive", person.can_drive),
                ("can sign", person.can_sign),
                ("has bank access", person.has_bank_access),
                ("has medical proxy", person.has_medical_proxy),
            )
            if has_it
        ]
        capabilities = ", ".join(capability_names) if capability_names else "no special capabilities recorded"
        lines.append(f"- {person.display_name} (role: {person.role.value}; {capabilities})")
    return "\n".join(lines)


def _constraints_block(constraints: tuple[Constraint, ...]) -> str:
    if not constraints:
        return "(no constraints recorded yet)"
    return "\n".join(
        f"- [{constraint.severity.value.upper()}/{constraint.kind.value}] {constraint.original_text}"
        for constraint in constraints
    )


def _obligations_block(obligations: tuple[Obligation, ...]) -> str:
    if not obligations:
        return "(none)"
    lines = []
    for obligation in obligations:
        due = obligation.due_at.isoformat() if obligation.due_at is not None else "no due date recorded"
        lines.append(f"- {obligation.title} (type: {obligation.obligation_type}; due: {due})")
    return "\n".join(lines)


class ImplicationAgent:
    """A12 Implication Agent. Dependency-injected on a `GeminiClient` —
    reads via a pre-assembled `ImplicationRequest` (see `context.py`),
    never a `GraphReader` directly, keeping this module's core reasoning
    logic decoupled from graph/Firestore mechanics entirely (hexagonal
    architecture)."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def imply(self, request: ImplicationRequest) -> ImplicationRunResult:
        """Derives implied obligations for one SOURCE_DOCUMENT.

        Args:
            request: the document text plus household context to reason
                against (`context.assemble_implication_request` builds
                this for a real graph).

        Returns:
            An `ImplicationRunResult` — `candidates` contains only
            citation-validated, confidence-cleared implied obligations;
            `discarded` records every rejected inference with a specific
            reason, never silently dropped.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape.
        """
        prompt = load_prompt("A12")
        context = request.household_context
        rendered = prompt.text.format(
            people_block=_people_block(context.people),
            constraints_block=_constraints_block(context.constraints),
            stated_obligations_block=_obligations_block(context.stated_obligations),
            open_obligations_block=_obligations_block(context.open_obligations),
            document_text=request.document_text,
        )

        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID,
            tier=ModelTier.PRO,
            prompt=rendered,
            thinking_budget=_ELEVATED_THINKING_BUDGET_TOKENS,
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_items = require_list(parsed, "candidates", agent_id=AGENT_ID)

        discarded: list[DiscardedInference] = []
        survivors: list[tuple[_RawCandidate, str, str, str]] = []
        """(raw, candidate_id, located_region, located_resolved_text)."""

        for item in raw_items:
            if not isinstance(item, dict):
                continue
            raw = self._parse_raw(item)

            validation = locate_and_validate_citation(
                claimed_span_text=raw.cited_span_text, document_text=request.document_text
            )
            if not validation.valid or validation.located is None:
                discarded.append(
                    DiscardedInference(
                        title=raw.title,
                        reasoning=raw.reasoning,
                        claimed_region=None,
                        claimed_span_text=raw.cited_span_text,
                        discard_reason=validation.reason or "claimed citation not locatable",
                    )
                )
                logger.info(
                    "agents.consequence.a12.discarded_uncitable",
                    title=raw.title,
                    reason=validation.reason,
                )
                continue

            if raw.confidence < _MIN_CANDIDATE_CONFIDENCE:
                discarded.append(
                    DiscardedInference(
                        title=raw.title,
                        reasoning=raw.reasoning,
                        claimed_region=validation.located.region,
                        claimed_span_text=raw.cited_span_text,
                        discard_reason=(
                            f"confidence {raw.confidence:.2f} below floor {_MIN_CANDIDATE_CONFIDENCE:.2f}"
                        ),
                    )
                )
                logger.info(
                    "agents.consequence.a12.discarded_low_confidence",
                    title=raw.title,
                    confidence=raw.confidence,
                )
                continue

            candidate_id = uuid.uuid4().hex
            survivors.append((raw, candidate_id, validation.located.region, validation.located.resolved_text))

        label_to_candidate_id = {raw.label: candidate_id for raw, candidate_id, _, _ in survivors}

        candidates: list[ImpliedObligationCandidate] = []
        for raw, candidate_id, region, resolved_text in survivors:
            depends_on_ids: list[str] = []
            dropped_labels: list[str] = []
            for dep_label in raw.depends_on_labels:
                if dep_label == raw.label:
                    continue
                resolved_id = label_to_candidate_id.get(dep_label)
                if resolved_id is None:
                    dropped_labels.append(dep_label)
                else:
                    depends_on_ids.append(resolved_id)
            if dropped_labels:
                logger.info(
                    "agents.consequence.a12.dropped_dependency_reference",
                    candidate_label=raw.label,
                    dropped_labels=dropped_labels,
                )

            citation = Citation(
                source_document_id=str(request.source_document_id),
                region=region,
                supports_claim=raw.title,
            )
            candidates.append(
                ImpliedObligationCandidate(
                    candidate_id=candidate_id,
                    title=raw.title,
                    obligation_type=raw.obligation_type,
                    due_at=raw.due_at,
                    effort_estimate_minutes=raw.effort_estimate_minutes,
                    reasoning=raw.reasoning,
                    citation=citation,
                    cited_span_text=resolved_text,
                    confidence=raw.confidence,
                    depends_on_candidate_ids=tuple(depends_on_ids),
                )
            )

        overall_confidence = (
            sum(candidate.confidence for candidate in candidates) / len(candidates) if candidates else 0.0
        )
        logger.info(
            "agents.consequence.a12.completed",
            source_document_id=str(request.source_document_id),
            candidate_count=len(candidates),
            discarded_count=len(discarded),
        )
        return ImplicationRunResult(
            candidates=tuple(candidates),
            discarded=tuple(discarded),
            model_tier="pro",
            prompt_version=prompt.version,
            confidence=overall_confidence,
            invocation_id=uuid.uuid4().hex,
        )

    def _parse_raw(self, item: dict[str, object]) -> _RawCandidate:
        label = require_str(item, "label", agent_id=AGENT_ID)
        depends_on_raw = require_list(item, "depends_on_labels", agent_id=AGENT_ID)
        return _RawCandidate(
            label=label,
            title=require_str(item, "title", agent_id=AGENT_ID),
            obligation_type=require_str(item, "obligation_type", agent_id=AGENT_ID),
            due_at=_parse_due_at(item.get("due_at"), label=label),
            effort_estimate_minutes=optional_int(item, "effort_estimate_minutes", agent_id=AGENT_ID),
            reasoning=require_str(item, "reasoning", agent_id=AGENT_ID),
            cited_span_text=require_str(item, "cited_span_text", agent_id=AGENT_ID),
            confidence=require_float(item, "confidence", agent_id=AGENT_ID, default=0.0),
            depends_on_labels=tuple(str(dep) for dep in depends_on_raw),
        )


__all__ = ["AGENT_ID", "ImplicationAgent"]
