"""A56 Fallback Coordinator's real escalation effect — turns a
`app.agents.concierge.types.FallbackDecision` into a real
`EscalationAgent.route()` call.

Mirrors `app.events.followup_dispatcher`'s exact Phase 7 precedent for
A31: the agent (`app.agents.concierge.fallback_coordinator_agent.
FallbackCoordinatorAgent`, under `backend/app/agents/`) decides and
produces plain data only — it holds zero import path into
`app.arbitration` (`test_action_construction_boundary.py`'s
`TestNoAgentImportsArbitration` is a structurally enforced boundary, not
a convention). This module, outside `backend/app/agents/`, is where the
real arbitration-touching call actually happens — the same reason A31
itself was never built under `backend/app/agents/` either.

A `FallbackDecision` with `action is FallbackAction.RETRY` has nothing for
this module to do — the caller (a Cloud Scheduler-driven retry loop,
outside this phase's scope, mirroring A31's own retry cadence) is
responsible for re-attempting the call at `retry_after`, not this module.
"""

from __future__ import annotations

import structlog
from contracts.graph_types import Person

from app.agents.concierge.types import FallbackAction, FallbackDecision, FallbackEscalationPayload
from app.arbitration.escalation_agent import EscalationAgent
from app.arbitration.types import EscalationContext, EscalationReason, EscalationRouting

logger = structlog.get_logger(__name__)


class FallbackDecisionNotEscalating(ValueError):
    """Raised when `dispatch_fallback_decision` is handed a `FallbackDecision`
    whose `action` is not `FallbackAction.ESCALATE` — calling this
    dispatcher for a `RETRY` decision is a caller error (there is a real
    retry-scheduling path for that, not this one), not a case to silently
    no-op on."""

    def __init__(self, *, action: FallbackAction) -> None:
        self.action = action
        super().__init__(
            f"dispatch_fallback_decision called with a non-ESCALATE decision (action={action.value!r}) — "
            "only an ESCALATE decision has a real effect for this dispatcher to perform"
        )


def _build_escalation_context(payload: FallbackEscalationPayload) -> EscalationContext:
    return EscalationContext(
        reason=EscalationReason.CONCIERGE_CALL_NEEDS_HUMAN,
        action_type=payload.action_type,
        summary=payload.summary,
        risk_tier=payload.risk_tier,
        involves_financial=False,
        involves_signature=False,
        involves_medical=False,
        evidence_bundle=payload.evidence_bundle,
        related_node_id=payload.related_node_id,
    )


def dispatch_fallback_decision(
    decision: FallbackDecision,
    *,
    escalation_agent: EscalationAgent,
    household_people: tuple[Person, ...],
) -> EscalationRouting:
    """Turns an `ESCALATE` `FallbackDecision` into a real
    `EscalationAgent.route()` call and returns the real `EscalationRouting`.

    Args:
        decision: must have `action is FallbackAction.ESCALATE` and a
            populated `escalation_payload` — anything else is a caller
            error (see `FallbackDecisionNotEscalating`).
        escalation_agent: the real, shared `EscalationAgent` (Phase 5) —
            never a second escalation mechanism.
        household_people: caller-assembled candidate pool, passed straight
            through to `EscalationAgent.route` — mirrors that method's own
            established "GraphReader has no enumerate-all primitive"
            precedent, identical to `followup_dispatcher.py`'s usage.

    Raises:
        FallbackDecisionNotEscalating: `decision.action` is not `ESCALATE`.
    """
    if decision.action is not FallbackAction.ESCALATE or decision.escalation_payload is None:
        raise FallbackDecisionNotEscalating(action=decision.action)

    context = _build_escalation_context(decision.escalation_payload)
    routing = escalation_agent.route(escalation=context, household_people=household_people)
    logger.info(
        "events.concierge_fallback_dispatcher.escalated",
        candidate_count=len(routing.candidate_person_ids),
    )
    return routing


__all__ = ["FallbackDecisionNotEscalating", "dispatch_fallback_decision"]
