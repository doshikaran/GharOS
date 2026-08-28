"""Tests for `app.events.concierge_fallback_dispatcher.dispatch_fallback_decision`
(A56's real escalation effect) — proves an `ESCALATE` `FallbackDecision`
reuses the real `app.arbitration.escalation_agent.EscalationAgent` (never
a second escalation mechanism, mirroring `test_followup_dispatcher.py`'s
identical Phase 7 precedent), and a `RETRY` decision is rejected rather
than silently no-oped on.
"""

from __future__ import annotations

import pytest
from contracts.actions import EvidenceBundle, RiskTier
from contracts.graph_types import NodeId

from app.agents.concierge.types import FallbackAction, FallbackDecision, FallbackEscalationPayload
from app.arbitration.escalation_agent import EscalationAgent
from app.arbitration.types import EscalationReason, EscalationRouting
from app.events.concierge_fallback_dispatcher import (
    FallbackDecisionNotEscalating,
    dispatch_fallback_decision,
)
from app.reasoning.gemini_client import GeminiClient
from tests._gemini_fakes import FakeModels, fake_router
from tests.conftest import make_person


def _escalation_agent(text: str = "A dentist call needs a human to take over.") -> EscalationAgent:
    return EscalationAgent(gemini_client=GeminiClient(router=fake_router(FakeModels(texts=[text]))))


def _escalate_decision(related_node_id: NodeId | None = None) -> FallbackDecision:
    if related_node_id is None:
        related_node_id = NodeId("obligation-1")
    payload = FallbackEscalationPayload(
        action_type="outbound_concierge_call",
        summary="2 automated attempts with Sunrise Dental did not result in a booking.",
        risk_tier=RiskTier.R2_APPROVE,
        evidence_bundle=EvidenceBundle(
            proposed_action="Book with Sunrise Dental",
            reasoning="2 automated attempts did not resolve.",
            evidence_consulted=("call outcome: clinic declined automated caller",),
            confidence=1.0,
            consequence_if_wrong="No automated path remains.",
        ),
        related_node_id=related_node_id,
    )
    return FallbackDecision(
        action=FallbackAction.ESCALATE,
        reasoning=payload.summary,
        retry_after=None,
        escalation_payload=payload,
    )


class TestEscalateDispatchesTheRealEscalationAgent:
    def test_escalate_decision_produces_a_real_escalation_routing(self) -> None:
        routing = dispatch_fallback_decision(
            _escalate_decision(),
            escalation_agent=_escalation_agent(),
            household_people=(make_person("person-dad", "Rohan", has_bank_access=True, can_sign=True),),
        )
        assert isinstance(routing, EscalationRouting)
        assert routing.reason is EscalationReason.CONCIERGE_CALL_NEEDS_HUMAN
        assert len(routing.candidate_person_ids) >= 1


class TestRetryDecisionIsRejected:
    def test_retry_decision_raises_rather_than_silently_no_opping(self) -> None:
        retry_decision = FallbackDecision(
            action=FallbackAction.RETRY,
            reasoning="retrying",
            retry_after=None,
            escalation_payload=None,
        )
        with pytest.raises(FallbackDecisionNotEscalating):
            dispatch_fallback_decision(
                retry_decision, escalation_agent=_escalation_agent(), household_people=()
            )
