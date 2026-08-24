"""A13 — Constraint Checker (spec §7.3 Stage 3, §15.4).

*Responsibility:* evaluate one candidate obligation against the
household's existing hard/soft CONSTRAINTs and report, per constraint,
whether it is violated. Never proposes a fix.

*Model tier:* Flash for the first pass ("lookup" — spec §15.4's own
wording), escalating to Pro-tier ("interpretation" — the spec's own
example: "does 'may contain traces' violate a nut allergy? yes, but
that's judgment") whenever Flash's own verdict is `"ambiguous"`, or
whenever the constraint is HARD and Flash's confidence does not clear
`_HARD_CONSTRAINT_CONFIDENCE_FLOOR` — the exact same two-pass escalation
shape `entity_resolution.EntityResolutionAgent` already establishes for
its own hard-constraint-bearing case, reused deliberately rather than
inventing a different pattern.

*Forbidden:* **resolving violations.** This module has no code path that
proposes a substitution, a fix, or an alternative — `ConstraintCheckFinding`
(the entire output shape) carries only a verdict and an explanation, never
a remedy.

*Failure:* **hard-constraint ambiguity always escalates.** If a HARD
constraint's verdict is still `"ambiguous"` after the Pro-tier pass,
`check` raises `contracts.errors.EscalationRequired` rather than
returning any finding for that constraint — structurally impossible for
a caller to mistake an unresolved hard-constraint check for a quiet "no
violation."

A cheap, deterministic (no LLM call) relevance prefilter
(`_plausibly_relevant`) skips SOFT constraints with no textual overlap at
all with the candidate — pure cost discipline; it never skips a HARD
constraint, ever, regardless of how little textual overlap there appears
to be.
"""

from __future__ import annotations

import re

import structlog
from contracts.agents import ModelTier
from contracts.errors import EscalationRequired
from contracts.graph_types import AgentId, Constraint, ConstraintSeverity

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiCallResult, GeminiClient
from .json_utils import parse_json_response, require_float, require_str
from .types import ConstraintCheckFinding, ImpliedObligationCandidate

AGENT_ID = AgentId("A13")

logger = structlog.get_logger(__name__)

_HARD_CONSTRAINT_CONFIDENCE_FLOOR = 0.85
"""Below this, a HARD constraint's Flash-tier verdict is not trusted on
its own — a Pro-tier pass runs before any finding is returned, even if
Flash's own verdict was `"no_violation"`. Mirrors
`entity_resolution._HARD_CONSTRAINT_CONFIDENCE_FLOOR`'s exact rationale."""

_RELEVANCE_TOKEN_PATTERN = re.compile(r"[a-zA-Z]{4,}")
"""Words of 4+ letters — short enough to catch real shared vocabulary
("lunch", "nuts", "sign"), long enough to skip noise words that would
make the prefilter useless."""


def _relevance_tokens(text: str) -> set[str]:
    return {match.group(0).lower() for match in _RELEVANCE_TOKEN_PATTERN.finditer(text)}


def _plausibly_relevant(candidate: ImpliedObligationCandidate, constraint: Constraint) -> bool:
    """Deterministic, LLM-free cost prefilter: `True` whenever the
    candidate and constraint share at least one real word, or whenever
    the constraint carries no comparable text at all (a constraint this
    module cannot even summarise is never silently skipped). **Never
    called for HARD constraints** — `check` always evaluates every HARD
    constraint via the model regardless of what this function would say."""
    constraint_blob = " ".join(
        (constraint.kind.value, constraint.original_text, *constraint.structured.values())
    )
    constraint_tokens = _relevance_tokens(constraint_blob)
    if not constraint_tokens:
        return True
    candidate_blob = " ".join((candidate.title, candidate.obligation_type, candidate.reasoning))
    return bool(_relevance_tokens(candidate_blob) & constraint_tokens)


class ConstraintCheckAgent:
    """A13 Constraint Checker. Dependency-injected on a `GeminiClient`."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def check(
        self, *, candidate: ImpliedObligationCandidate, constraints: tuple[Constraint, ...]
    ) -> tuple[ConstraintCheckFinding, ...]:
        """Checks `candidate` against every constraint in `constraints`
        that is either HARD or passes the deterministic relevance
        prefilter.

        Args:
            candidate: the obligation candidate to check (typically one of
                A12's `ImpliedObligationCandidate`s, but any obligation-
                shaped candidate works — this module never reads a
                `GraphReader` itself).
            constraints: the household's current CONSTRAINT nodes to check
                against (`HouseholdContext.constraints`).

        Returns:
            One `ConstraintCheckFinding` per constraint actually
            evaluated — SOFT constraints skipped by the relevance
            prefilter produce no finding at all (not a "no_violation"
            finding, which would falsely claim the check happened).

        Raises:
            errors.ModelResponseMalformed: a model response could not be
                parsed as the expected JSON shape.
            contracts.errors.EscalationRequired: a HARD constraint's
                verdict is still `"ambiguous"` after Pro-tier escalation.
        """
        findings: list[ConstraintCheckFinding] = []
        for constraint in constraints:
            is_hard = constraint.severity is ConstraintSeverity.HARD
            if not is_hard and not _plausibly_relevant(candidate, constraint):
                continue
            findings.append(self._check_one(candidate, constraint, is_hard=is_hard))
        return tuple(findings)

    def _check_one(
        self, candidate: ImpliedObligationCandidate, constraint: Constraint, *, is_hard: bool
    ) -> ConstraintCheckFinding:
        prompt = load_prompt("A13")
        rendered = prompt.text.format(
            candidate_title=candidate.title,
            candidate_type=candidate.obligation_type,
            candidate_due_at=(
                candidate.due_at.isoformat() if candidate.due_at is not None else "not specified"
            ),
            candidate_reasoning=candidate.reasoning,
            constraint_kind=constraint.kind.value,
            constraint_severity=constraint.severity.value,
            constraint_structured=constraint.structured,
            constraint_original_text=constraint.original_text,
        )

        flash = self._call(rendered, tier=ModelTier.FLASH)
        verdict, confidence, explanation = flash
        escalated = False
        needs_escalation = verdict == "ambiguous" or (
            is_hard and confidence < _HARD_CONSTRAINT_CONFIDENCE_FLOOR
        )
        if needs_escalation:
            verdict, confidence, explanation = self._call(rendered, tier=ModelTier.PRO)
            escalated = True

        if is_hard and verdict == "ambiguous":
            logger.warning(
                "agents.consequence.a13.hard_constraint_ambiguity_escalated",
                candidate_id=candidate.candidate_id,
                constraint_id=str(constraint.id),
            )
            raise EscalationRequired(
                reason=(
                    f"hard constraint {constraint.id} could not be confidently checked against "
                    f"candidate obligation '{candidate.title}' — ambiguous even after Pro-tier review"
                ),
                context={
                    "candidate_id": candidate.candidate_id,
                    "constraint_id": str(constraint.id),
                    "explanation": explanation,
                },
            )

        return ConstraintCheckFinding(
            candidate_id=candidate.candidate_id,
            constraint_id=constraint.id,
            constraint_kind=constraint.kind,
            severity=constraint.severity,
            violates=(verdict == "violates"),
            explanation=explanation,
            confidence=confidence,
            escalated_to_pro=escalated,
        )

    def _call(self, rendered_prompt: str, *, tier: ModelTier) -> tuple[str, float, str]:
        call_result: GeminiCallResult = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=tier, prompt=rendered_prompt
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        verdict = require_str(parsed, "verdict", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        explanation = require_str(parsed, "explanation", agent_id=AGENT_ID)
        return verdict, confidence, explanation


__all__ = ["AGENT_ID", "ConstraintCheckAgent"]
