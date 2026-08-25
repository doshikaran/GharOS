"""Tests for `app.arbitration.escalation_agent.EscalationAgent` — A58.

Capability-based routing (`has_bank_access` / `can_sign` /
`has_medical_proxy`) and the honest DEBT-006 degradation ("no finer
capability signal -> notify all adults") are both proven directly against
`contracts.graph_types.Person`'s real fields — no invented field.
"""

from __future__ import annotations

from dataclasses import replace

from contracts.actions import RiskTier
from contracts.graph_types import NodeId, Person, PersonRole
from google.genai import errors as genai_errors

from app.arbitration.escalation_agent import AGENT_ID, EscalationAgent
from app.arbitration.types import EscalationContext, EscalationReason
from app.reasoning.gemini_client import GeminiClient
from tests.conftest import make_person

from ._gemini_fakes import FakeModels, fake_router


def _people() -> tuple[Person, ...]:
    dad = make_person("person-dad", "Rohan", has_bank_access=True, can_sign=True)
    mom = make_person("person-mom", "Priya", has_bank_access=False, can_sign=True)
    kid = replace(make_person("person-kid", "Aarav"), role=PersonRole.CHILD)
    return (dad, mom, kid)


def _agent_with_response(text: str) -> EscalationAgent:
    fake_models = FakeModels(texts=[text])
    client = GeminiClient(router=fake_router(fake_models))
    return EscalationAgent(gemini_client=client)


def _agent_that_fails() -> EscalationAgent:
    api_error = genai_errors.APIError(503, {"error": {"message": "simulated Gemini outage"}})
    fake_models = FakeModels(texts=["irrelevant"], error=api_error)
    client = GeminiClient(router=fake_router(fake_models))
    return EscalationAgent(gemini_client=client)


def _context(
    *,
    reason: EscalationReason = EscalationReason.APPROVAL_EXPIRED,
    involves_financial: bool = False,
    involves_signature: bool = False,
    involves_medical: bool = False,
) -> EscalationContext:
    return EscalationContext(
        reason=reason,
        action_type="pay_dues",
        summary="Monthly society dues approval expired before anyone reviewed it.",
        risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
        involves_financial=involves_financial,
        involves_signature=involves_signature,
        involves_medical=involves_medical,
        evidence_bundle=None,
        related_node_id=NodeId("ledger-event-1"),
    )


class TestCapabilityBasedRouting:
    def test_financial_escalation_routes_to_bank_access_holders(self) -> None:
        agent = _agent_with_response("Approve the dues payment or let it lapse.")
        routing = agent.route(escalation=_context(involves_financial=True), household_people=_people())
        assert routing.candidate_person_ids == (NodeId("person-dad"),)
        assert "has_bank_access" in routing.routing_basis

    def test_signature_escalation_routes_to_can_sign_holders(self) -> None:
        agent = _agent_with_response("Someone needs to sign this permission slip.")
        routing = agent.route(escalation=_context(involves_signature=True), household_people=_people())
        assert set(routing.candidate_person_ids) == {NodeId("person-dad"), NodeId("person-mom")}
        assert "can_sign" in routing.routing_basis

    def test_medical_escalation_routes_to_medical_proxy_holders_or_degrades_honestly(self) -> None:
        agent = _agent_with_response("A medical choice needs a decision.")
        routing = agent.route(escalation=_context(involves_medical=True), household_people=_people())
        # None of the fixture people have has_medical_proxy=True -> honest
        # degradation to "notify all adults", never an invented signal.
        assert set(routing.candidate_person_ids) == {NodeId("person-dad"), NodeId("person-mom")}
        assert "DEBT-006" in routing.routing_basis

    def test_general_escalation_with_no_finer_signal_notifies_all_adults(self) -> None:
        agent = _agent_with_response("An approval expired; please review.")
        routing = agent.route(escalation=_context(), household_people=_people())
        assert set(routing.candidate_person_ids) == {NodeId("person-dad"), NodeId("person-mom")}
        assert "person-kid" not in [str(p) for p in routing.candidate_person_ids]
        assert "DEBT-006" in routing.routing_basis

    def test_no_adults_at_all_degrades_to_everyone(self) -> None:
        agent = _agent_with_response("Escalation with no adults on record.")
        kid_only = (replace(make_person("person-kid", "Aarav"), role=PersonRole.CHILD),)
        routing = agent.route(escalation=_context(), household_people=kid_only)
        assert routing.candidate_person_ids == (NodeId("person-kid"),)


class TestBriefingComposition:
    def test_briefing_uses_the_flash_call_on_success(self) -> None:
        agent = _agent_with_response("A clear, human-readable briefing.")
        routing = agent.route(escalation=_context(), household_people=_people())
        assert routing.briefing == "A clear, human-readable briefing."
        assert routing.briefing_is_template_fallback is False

    def test_briefing_falls_back_to_a_template_on_call_failure_never_drops_the_escalation(self) -> None:
        agent = _agent_that_fails()
        routing = agent.route(escalation=_context(), household_people=_people())
        assert routing.briefing_is_template_fallback is True
        assert routing.briefing  # never empty -- the escalation must always reach the human with *something*
        assert "pay_dues" in routing.briefing


class TestAgentIdentity:
    def test_agent_id_is_a58(self) -> None:
        assert str(AGENT_ID) == "A58"
