"""Tests for A24 Unblocker / Preparation
(`app.agents.intention_action.unblocker_agent`).

PHASES.md Phase 9's own acceptance list, this module's share of it:
- Information blocker -> fact fetched (a real graph query, never a
  fabricated fact when nothing is found).
- Decision blocker -> narrowed to binary.
- Aversion blocker -> modality switched (never the same modality back).
- Forbidden: send without approval — T0 read only, no gated tool import.

Unit tests only (fake Gemini, no network; `FakeGraphReader` in place of
the Firestore emulator for the T0 read path).
"""

from __future__ import annotations

import ast
import inspect
import json
import types

import pytest
from contracts.graph_types import EdgeType, NodeId
from contracts.tools import PermissionTier

from app.agents.intention_action import unblocker_agent
from app.agents.intention_action.errors import ModelResponseMalformed
from app.agents.intention_action.types import (
    DecisionNarrowingRequest,
    FirstStepDecompositionRequest,
    GraphQuerySpec,
    InformationFetchRequest,
    ModalitySwitchRequest,
)
from app.agents.intention_action.unblocker_agent import AGENT_ID, UnblockerAgent
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied, ToolTierNotPermitted

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_reader import FakeGraphReader
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router


class _DummyT3Tool:
    """A minimal `contracts.tools.Registrable` test double at T3 — mirrors
    `test_reconciliation_agent.py`'s identical helper: proves this
    agent's registry rejects a write tool even though T3 is not itself in
    `GATED_TIERS` (the allowed-tiers check, not the gated-tier-origin
    check, is what must catch this one)."""

    def __init__(self) -> None:
        self.name = "graph_writer"
        self.tier = PermissionTier.T3_INTERNAL_WRITE


class _FakeProvider:
    def __init__(self, phone: str) -> None:
        self.phone = phone


def _booked_with_query() -> GraphQuerySpec:
    return GraphQuerySpec(
        operation="neighbours", args={"node_id": "obligation-dentist", "edge_type": EdgeType.BOOKED_WITH}
    )


def _agent(*, texts: list[str] | None = None, reader: FakeGraphReader | None = None) -> UnblockerAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return UnblockerAgent(
        gemini_client=GeminiClient(router=fake_router(fake_models)),
        graph_reader=reader or FakeGraphReader(),
    )


class TestFetchInformation:
    def test_fact_found_and_phrased(self) -> None:
        provider = _FakeProvider(phone="+91-98765-43210")
        reader = FakeGraphReader(
            neighbours_by_node_and_type={("obligation-dentist", EdgeType.BOOKED_WITH): (provider,)}
        )
        response = json.dumps(
            {"fact_text": "The dentist's phone number is +91-98765-43210.", "confidence": 0.9}
        )
        agent = _agent(texts=[response], reader=reader)
        request = InformationFetchRequest(
            obligation_id=NodeId("obligation-dentist"),
            person_id=NodeId("person-aarav"),
            missing_fact_description="the dentist's phone number",
            query=_booked_with_query(),
        )

        result = agent.fetch_information(request)

        assert result.fetched is True
        assert result.fact_text == "The dentist's phone number is +91-98765-43210."
        assert result.model_tier == "flash"

    def test_nothing_found_never_fabricates_a_fact(self) -> None:
        reader = FakeGraphReader(neighbours_by_node_and_type={})
        agent = _agent(texts=["should never be read"], reader=reader)
        request = InformationFetchRequest(
            obligation_id=NodeId("obligation-dentist"),
            person_id=NodeId("person-aarav"),
            missing_fact_description="the dentist's phone number",
            query=_booked_with_query(),
        )

        result = agent.fetch_information(request)

        assert result.fetched is False
        assert result.fact_text is None
        assert result.confidence == 0.0


class TestNarrowDecision:
    def test_narrows_to_two_distinct_options(self) -> None:
        response = json.dumps(
            {
                "option_a": "Renew the same plan for another year",
                "option_b": "Switch providers before the deadline",
                "framing_text": "It comes down to: renew or switch.",
                "reasoning": "both real options surfaced so far",
                "confidence": 0.7,
            }
        )
        agent = _agent(texts=[response])
        request = DecisionNarrowingRequest(
            obligation_id=NodeId("obligation-internet"),
            person_id=NodeId("person-priya"),
            decision_summary="whether to renew the internet plan",
            known_options=("renew", "switch"),
            known_facts=("current plan expires in 10 days",),
        )

        result = agent.narrow_decision(request)

        assert result.option_a != result.option_b
        assert result.model_tier == "pro"

    def test_identical_options_rejected(self) -> None:
        response = json.dumps(
            {
                "option_a": "Renew the plan",
                "option_b": "renew the plan",
                "framing_text": "n/a",
                "reasoning": "n/a",
                "confidence": 0.5,
            }
        )
        agent = _agent(texts=[response])
        request = DecisionNarrowingRequest(
            obligation_id=NodeId("obligation-internet"),
            person_id=NodeId("person-priya"),
            decision_summary="whether to renew",
            known_options=(),
            known_facts=(),
        )

        with pytest.raises(ModelResponseMalformed):
            agent.narrow_decision(request)


class TestSwitchModality:
    def test_switches_to_a_different_modality_with_predrafted_text(self) -> None:
        response = json.dumps(
            {
                "to_modality": "message",
                "pre_drafted_text": "Hi, could you confirm my appointment for Friday? Thanks.",
                "reasoning": "this person avoids phone calls but responds well to messages",
                "confidence": 0.8,
            }
        )
        agent = _agent(texts=[response])
        request = ModalitySwitchRequest(
            obligation_id=NodeId("obligation-dentist"),
            person_id=NodeId("person-aarav"),
            avoided_modality="call",
            task_summary="confirm the dentist appointment",
            counterparty_name="City Dental Clinic",
            known_facts=("clinic accepts WhatsApp messages",),
        )

        result = agent.switch_modality(request)

        assert result.from_modality == "call"
        assert result.to_modality == "message"
        assert "Friday" in result.pre_drafted_text

    def test_same_modality_back_is_rejected(self) -> None:
        response = json.dumps(
            {
                "to_modality": "call",
                "pre_drafted_text": "n/a",
                "reasoning": "n/a",
                "confidence": 0.5,
            }
        )
        agent = _agent(texts=[response])
        request = ModalitySwitchRequest(
            obligation_id=NodeId("obligation-dentist"),
            person_id=NodeId("person-aarav"),
            avoided_modality="call",
            task_summary="confirm the appointment",
            counterparty_name="City Dental Clinic",
            known_facts=(),
        )

        with pytest.raises(ModelResponseMalformed):
            agent.switch_modality(request)


class TestDecomposeFirstStep:
    def test_produces_one_concrete_first_action(self) -> None:
        response = json.dumps(
            {
                "first_action_text": "Find the AC service company's number in last year's receipt.",
                "estimated_minutes": 5,
                "reasoning": "the smallest real first step",
                "confidence": 0.75,
            }
        )
        agent = _agent(texts=[response])
        request = FirstStepDecompositionRequest(
            obligation_id=NodeId("obligation-ac-service"),
            person_id=NodeId("person-priya"),
            task_summary="get the AC serviced",
            known_facts=("last serviced a year ago",),
        )

        result = agent.decompose_first_step(request)

        assert result.first_action_text.startswith("Find the AC service company's number")
        assert result.estimated_minutes == 5


class TestToolRegistryIsT0Only:
    def test_registry_holds_only_a_t0_tool(self) -> None:
        agent = _agent()
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T0_READ

    def test_registry_rejects_a_t4_send_tool(self) -> None:
        agent = _agent()
        send_tool = ReferenceGatedTool(
            name="message_sender",
            tier=PermissionTier.T4_EXTERNAL_COMMUNICATION,
            bounds={},
            effect=lambda **kwargs: "sent",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, send_tool)
        assert not agent.tool_registry.has_tier(PermissionTier.T4_EXTERNAL_COMMUNICATION)

    def test_registry_rejects_a_t3_write_tool(self) -> None:
        """Not just gated tiers — this agent's own registry ceiling caps
        at T0, so even an ungated T3 write tool must be refused (mirrors
        `test_reconciliation_agent.py`'s `_DummyT3Tool` precedent)."""
        agent = _agent()
        with pytest.raises(ToolTierNotPermitted):
            agent.tool_registry.register(_DummyT3Tool())
        assert not agent.tool_registry.has_tier(PermissionTier.T3_INTERNAL_WRITE)


def _references_gated_tool_machinery(module: types.ModuleType) -> bool:
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ImportFrom)
            and node.module
            and ("arbitration" in node.module or "ApprovalGatedTool" in (a.name for a in node.names))
        ):
            return True
    return False


class TestForbiddenBehaviour:
    """spec §15.9 A24 forbidden list: 'send without approval.'"""

    def test_module_has_no_gated_tool_import(self) -> None:
        assert not _references_gated_tool_machinery(unblocker_agent)


def test_agent_id_is_a24() -> None:
    assert str(AGENT_ID) == "A24"
