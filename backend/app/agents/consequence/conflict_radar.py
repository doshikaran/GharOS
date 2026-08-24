"""A14 — Conflict Radar (spec §7.3 Stage 3, §15.4).

*Responsibility:* detect temporal, resource, capability, and load
conflicts — both among the household's existing graph-resident
obligations, and between newly implied candidates (A12's output, not yet
written to the graph) and everything else.

*Two layers, in order, matching the resume brief exactly ("call this
first, then reason further only where needed"):*

1. **Deterministic layer** — `app.solvers.conflict_prepass.
   DeterministicConflictPrepass` (E1), run over the household's
   graph-resident obligations (`HouseholdContext.stated_obligations` +
   `HouseholdContext.open_obligations` — real `Obligation` nodes with real
   `OWNED_BY` edges the prepass can resolve). No LLM call. This is what
   catches spec §7.3's canonical field-trip fixture: a 1:30pm early pickup
   already stated from the document colliding with an existing 1:00pm
   work meeting already in the graph.

2. **Reasoning layer** — Pro-tier Gemini, run only over A12's newly
   *implied* `candidates`, and only when there is at least one. **Why
   these cannot go through the deterministic layer too:** a fresh
   `ImpliedObligationCandidate` has no graph presence yet — no `id` in the
   store, no `OWNED_BY` edge — because A15 (Obligation Writer) has not run
   yet at this pipeline stage (spec §7.3: DECONFLICT happens before OWN).
   `DeterministicConflictPrepass` resolves owners via
   `GraphReader.neighbours(obligation.id, EdgeType.OWNED_BY)`, which
   cannot resolve anything for an id that does not exist in the graph.
   Judging who would plausibly end up responsible for a brand-new
   candidate, and whether that creates a real collision, is exactly the
   kind of judgment call this reasoning layer exists for — it is given
   the deterministic layer's own findings so it never re-reports them.

*Forbidden:* **unilaterally resolving a multi-person conflict.**
`ConflictFinding` (this module's entire output shape) has no field for a
proposed resolution — structurally, this module cannot suggest one.

*Cost discipline:* the Pro-tier call is skipped entirely when
`candidates` is empty — no LLM call happens just to confirm "nothing new
to check."
"""

from __future__ import annotations

from datetime import datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId, Obligation, Person

from app.solvers.conflict_prepass import (
    CapabilityConflict,
    ConflictCandidate,
    ConflictPrepassResult,
    DeterministicConflictPrepass,
    LoadConflict,
    ResourceConflict,
    TemporalConflict,
)

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_float, require_list, require_str
from .types import ConflictFinding, ConflictKind, HouseholdContext, ImpliedObligationCandidate

AGENT_ID = AgentId("A14")

logger = structlog.get_logger(__name__)

_VALID_CONFLICT_KINDS: frozenset[str] = frozenset(("temporal", "resource", "capability", "load"))
_EMPTY_PREPASS_RESULT = ConflictPrepassResult(
    temporal=(), resource=(), capability=(), load=(), resource_detection_skipped=True
)


def _deterministic_candidate_to_finding(candidate: ConflictCandidate) -> ConflictFinding:
    """Maps one `app.solvers.conflict_prepass.ConflictCandidate` variant
    into this package's `ConflictFinding` shape. Deterministic findings
    carry `confidence=1.0` — they are exact arithmetic over real
    timestamps/flags, not a model's guess, and `from_deterministic_prepass
    =True` so a caller/test can tell the two layers apart."""
    if isinstance(candidate, TemporalConflict):
        return ConflictFinding(
            kind="temporal",
            subject_candidate_id=str(candidate.obligation_a_id),
            other_id=str(candidate.obligation_b_id),
            explanation=candidate.detail,
            confidence=1.0,
            from_deterministic_prepass=True,
        )
    if isinstance(candidate, ResourceConflict):
        return ConflictFinding(
            kind="resource",
            subject_candidate_id=str(candidate.obligation_a_id),
            other_id=str(candidate.obligation_b_id),
            explanation=candidate.detail,
            confidence=1.0,
            from_deterministic_prepass=True,
        )
    if isinstance(candidate, CapabilityConflict):
        return ConflictFinding(
            kind="capability",
            subject_candidate_id=str(candidate.obligation_id),
            other_id=f"capability:{candidate.missing_capability}",
            explanation=candidate.detail,
            confidence=1.0,
            from_deterministic_prepass=True,
        )
    if isinstance(candidate, LoadConflict):
        return ConflictFinding(
            kind="load",
            subject_candidate_id=str(candidate.person_id),
            other_id=f"window:{candidate.window[0].isoformat()}..{candidate.window[1].isoformat()}",
            explanation=candidate.detail,
            confidence=1.0,
            from_deterministic_prepass=True,
        )
    raise AssertionError(f"unhandled ConflictCandidate variant: {type(candidate)!r}")  # pragma: no cover


def _candidates_block(candidates: tuple[ImpliedObligationCandidate, ...]) -> str:
    if not candidates:
        return "(none)"
    lines = []
    for candidate in candidates:
        due = candidate.due_at.isoformat() if candidate.due_at is not None else "no due date"
        lines.append(
            f"- id={candidate.candidate_id} \"{candidate.title}\" (type: {candidate.obligation_type}; "
            f"due: {due}; reasoning: {candidate.reasoning})"
        )
    return "\n".join(lines)


def _obligations_block(obligations: tuple[Obligation, ...]) -> str:
    if not obligations:
        return "(none)"
    lines = []
    for obligation in obligations:
        due = obligation.due_at.isoformat() if obligation.due_at is not None else "no due date"
        lines.append(
            f'- id={obligation.id} "{obligation.title}" '
            f"(type: {obligation.obligation_type}; due: {due})"
        )
    return "\n".join(lines)


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
        lines.append(f"- {person.display_name} (id: {person.id}; {capabilities})")
    return "\n".join(lines)


def _deterministic_findings_block(findings: tuple[ConflictFinding, ...]) -> str:
    if not findings:
        return "(none found)"
    return "\n".join(f"- [{finding.kind}] {finding.explanation}" for finding in findings)


class ConflictRadar:
    """A14 Conflict Radar. Dependency-injected on a `GeminiClient` and a
    `DeterministicConflictPrepass` (E1's module) — never constructs either
    itself."""

    def __init__(self, *, gemini_client: GeminiClient, prepass: DeterministicConflictPrepass) -> None:
        self._gemini_client = gemini_client
        self._prepass = prepass

    def detect(
        self,
        *,
        candidates: tuple[ImpliedObligationCandidate, ...],
        household_context: HouseholdContext,
        fairness_threshold_minutes: float,
        load_window: tuple[datetime, datetime],
    ) -> tuple[ConflictFinding, ...]:
        """Runs the deterministic pre-pass over the household's
        graph-resident obligations, then (only if `candidates` is
        non-empty) a Pro-tier reasoning pass over the newly implied
        candidates.

        Args:
            candidates: A12's newly implied candidates for this run — may
                be empty (a pure re-check of existing graph state).
            household_context: household state to check against.
            fairness_threshold_minutes: forwarded to the deterministic
                pre-pass's load check.
            load_window: forwarded to the deterministic pre-pass's load
                check.

        Returns:
            Every finding from both layers, deterministic first.

        Raises:
            errors.ModelResponseMalformed: the reasoning-layer model
                response could not be parsed as the expected JSON shape.
        """
        graph_resident = household_context.stated_obligations + household_context.open_obligations
        prepass_result = (
            self._prepass.run(
                graph_resident,
                fairness_threshold_minutes=fairness_threshold_minutes,
                load_window=load_window,
            )
            if graph_resident
            else _EMPTY_PREPASS_RESULT
        )
        deterministic_findings = tuple(
            _deterministic_candidate_to_finding(candidate) for candidate in prepass_result.all_candidates()
        )
        logger.info(
            "agents.consequence.a14.deterministic_pass_completed",
            graph_resident_count=len(graph_resident),
            deterministic_finding_count=len(deterministic_findings),
        )

        if not candidates:
            return deterministic_findings

        reasoning_findings = self._reason(
            candidates=candidates,
            existing_obligations=graph_resident,
            people=household_context.people,
            deterministic_findings=deterministic_findings,
        )
        return deterministic_findings + reasoning_findings

    def _reason(
        self,
        *,
        candidates: tuple[ImpliedObligationCandidate, ...],
        existing_obligations: tuple[Obligation, ...],
        people: tuple[Person, ...],
        deterministic_findings: tuple[ConflictFinding, ...],
    ) -> tuple[ConflictFinding, ...]:
        prompt = load_prompt("A14")
        rendered = prompt.text.format(
            deterministic_findings_block=_deterministic_findings_block(deterministic_findings),
            candidates_block=_candidates_block(candidates),
            existing_obligations_block=_obligations_block(existing_obligations),
            people_block=_people_block(people),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        findings: list[ConflictFinding] = []
        for item in require_list(parsed, "conflicts", agent_id=AGENT_ID):
            if not isinstance(item, dict):
                continue
            kind_raw = require_str(item, "kind", agent_id=AGENT_ID)
            if kind_raw not in _VALID_CONFLICT_KINDS:
                logger.warning("agents.consequence.a14.dropped_unknown_conflict_kind", kind=kind_raw)
                continue
            # narrowed by the membership check above
            kind: ConflictKind = kind_raw  # type: ignore[assignment]
            findings.append(
                ConflictFinding(
                    kind=kind,
                    subject_candidate_id=require_str(item, "subject_id", agent_id=AGENT_ID),
                    other_id=require_str(item, "other_reference", agent_id=AGENT_ID),
                    explanation=require_str(item, "explanation", agent_id=AGENT_ID),
                    confidence=require_float(item, "confidence", agent_id=AGENT_ID, default=0.0),
                    from_deterministic_prepass=False,
                )
            )
        return tuple(findings)


__all__ = ["AGENT_ID", "ConflictRadar"]
