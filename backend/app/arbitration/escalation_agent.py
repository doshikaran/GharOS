"""A58 — Escalation Agent (spec §15.12, PHASES.md Phase 5).

*Responsibility:* route an escalation (expired approval, R4 action,
low-confidence discard) to the right household member — "capability- and
availability-aware" (spec's own wording) — with enough context to decide.

*Model tier:* Flash (spec §15.12, verbatim: "A58 — Escalation Agent...
Flash"). Candidate *selection* is plain deterministic code over
`contracts.graph_types.Person`'s existing boolean capability fields — no
model call needed for a lookup this cheap (cost discipline, spec §21.1).
The one Flash call this module makes is composing the human-readable
briefing text spec §15.12 calls "enough context to decide" — every
escalation gets one, since every escalation needs a briefing, not just
borderline ones (unlike A57's Pro-tier call, this is not a cost-driven
skip/call decision).

**Honest scope note (raised per this phase's own instructions, not
routed around):** spec §15.12 says "capability- and availability-aware."
`contracts.graph_types.Person` (frozen, CTO-owned) has **no `availability`
field** — DEBT-006 (first raised in `app.agents.consequence.context`'s
Phase 4 docstring) already documents this gap for a different consumer.
This module is genuinely **capability**-aware (`can_sign`, `has_bank_
access`, `has_medical_proxy`) but *not* availability-aware — there is no
real signal on the frozen contract to be aware of yet. Where no finer
capability signal applies to a given escalation, this module degrades
honestly to "notify every adult" (`PersonRole.ADULT`) rather than
inventing a field or guessing at availability.
"""

from __future__ import annotations

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId, Person, PersonRole

from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiClient

from .types import EscalationContext, EscalationRouting

AGENT_ID = AgentId("A58")

logger = structlog.get_logger(__name__)

_NO_FINER_SIGNAL_BASIS = (
    "no finer capability signal applies to this escalation (DEBT-006: contracts.graph_types.Person has no "
    "availability field yet) — notified every adult household member"
)

_BRIEFING_PROMPT = """You are the Escalation Agent for a household operating system. Compose a short, \
clear briefing (2-4 sentences) that gives a household member enough context to decide on the \
escalation below, without making the decision for them.

Escalation reason: {reason}
Action type: {action_type}
Summary: {summary}
Risk tier: {risk_tier}
Reasoning/evidence, if available: {reasoning}

Respond with the briefing text only — no JSON, no markdown, no preamble like "Here is the briefing:"."""


def _template_briefing(escalation: EscalationContext, candidate_count: int) -> str:
    """Deterministic fallback briefing — used only when the Flash call
    itself fails (see `EscalationAgent._compose_briefing`). An escalation
    must always reach its recipient with *some* usable context; a failed
    LLM call must never silently drop the escalation (fallback-ladder
    principle, `.claude/agents/e3.md`: "the human's cost is one minute,
    not fifteen") — but the fallback is honestly plain, not a fabricated
    LLM-quality summary."""
    tier_text = f" (risk tier {escalation.risk_tier.value})" if escalation.risk_tier is not None else ""
    return (
        f"Escalation ({escalation.reason.value}){tier_text}: {escalation.action_type}. {escalation.summary} "
        f"Notified {candidate_count} household member(s) for a decision — automated briefing unavailable, "
        "see the evidence bundle for full detail."
    )


class EscalationAgent:
    """A58. Dependency-injected on a `GeminiClient` for the briefing call."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def route(
        self, *, escalation: EscalationContext, household_people: tuple[Person, ...]
    ) -> EscalationRouting:
        """Args:
        escalation: what is being escalated and why.
        household_people: the candidate pool this escalation may route to
            — passed in by the caller (mirrors `app.agents.consequence.
            context.gather_household_context`'s established pattern:
            `contracts.repositories.GraphReader` has no "list every
            PERSON" primitive, so callers assemble the candidate pool
            themselves rather than this agent enumerating the graph).

        Returns:
            An `EscalationRouting` naming who to notify, why, and with
            what briefing text.
        """
        candidates, basis = self._select_candidates(escalation, household_people)
        briefing, is_fallback = self._compose_briefing(escalation, candidate_count=len(candidates))
        routing = EscalationRouting(
            reason=escalation.reason,
            candidate_person_ids=tuple(person.id for person in candidates),
            routing_basis=basis,
            briefing=briefing,
            briefing_is_template_fallback=is_fallback,
        )
        logger.info(
            "arbitration.escalation_agent.routed",
            reason=escalation.reason.value,
            action_type=escalation.action_type,
            candidate_count=len(candidates),
            routing_basis=basis,
        )
        return routing

    def _select_candidates(
        self, escalation: EscalationContext, people: tuple[Person, ...]
    ) -> tuple[tuple[Person, ...], str]:
        adults = tuple(person for person in people if person.role is PersonRole.ADULT)
        pool = adults if adults else people

        if escalation.involves_financial:
            matched = tuple(person for person in pool if person.has_bank_access)
            if matched:
                return matched, "has_bank_access capability (financial escalation)"
        if escalation.involves_signature:
            matched = tuple(person for person in pool if person.can_sign)
            if matched:
                return matched, "can_sign capability (signature/authorisation escalation)"
        if escalation.involves_medical:
            matched = tuple(person for person in pool if person.has_medical_proxy)
            if matched:
                return matched, "has_medical_proxy capability (medical escalation)"

        return pool, _NO_FINER_SIGNAL_BASIS

    def _compose_briefing(self, escalation: EscalationContext, *, candidate_count: int) -> tuple[str, bool]:
        risk_tier_text = escalation.risk_tier.value if escalation.risk_tier is not None else "n/a"
        reasoning_text = (
            escalation.evidence_bundle.reasoning if escalation.evidence_bundle is not None else "(none)"
        )
        prompt = _BRIEFING_PROMPT.format(
            reason=escalation.reason.value,
            action_type=escalation.action_type,
            summary=escalation.summary,
            risk_tier=risk_tier_text,
            reasoning=reasoning_text,
        )
        try:
            call_result = self._gemini_client.generate_text(
                agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=prompt
            )
        except GeminiCallFailed as exc:
            logger.warning(
                "arbitration.escalation_agent.briefing_call_failed",
                action_type=escalation.action_type,
                reason=str(exc),
            )
            return _template_briefing(escalation, candidate_count), True
        return call_result.text.strip(), False


__all__ = ["AGENT_ID", "EscalationAgent"]
