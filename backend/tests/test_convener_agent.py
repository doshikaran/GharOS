"""Tests for A41 Council Convener (`app.agents.council.convener_agent`).

Covers: real specialist/delegate id validation against the real five and
the real household member pool, the "holding a position itself" forbidden
behaviour being structurally impossible (no field on `CouncilComposition`
could carry one), T3-only tool registry, and the real `Decision` write.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from contracts.graph_types import Decision, DecisionStatus, NodeId
from contracts.tools import PermissionTier

from app.agents.council.convener_agent import AGENT_ID, CouncilConvenerAgent
from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.types import ConvenerRequest, CouncilComposition, HouseholdMemberSummary
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_MEMBERS = (
    HouseholdMemberSummary(
        person_id=NodeId("person-dad"), display_name="Dad", role="adult", materially_affected_note=None
    ),
    HouseholdMemberSummary(
        person_id=NodeId("person-mum"), display_name="Mum", role="adult", materially_affected_note=None
    ),
    HouseholdMemberSummary(
        person_id=NodeId("person-elder"),
        display_name="Grandma",
        role="elder",
        materially_affected_note="mobility constraint on file",
    ),
)


def _agent(*, texts: list[str]) -> tuple[CouncilConvenerAgent, FakeGraphWriter]:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    writer = FakeGraphWriter()
    agent = CouncilConvenerAgent(
        gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
    )
    return agent, writer


class TestRealComposition:
    def test_convene_writes_open_decision_and_returns_real_composition(self) -> None:
        agent, writer = _agent(
            texts=[
                json.dumps(
                    {
                        "convened_specialist_ids": ["A42", "A43", "A45"],
                        "convened_delegate_person_ids": ["person-dad", "person-mum", "person-elder"],
                    }
                )
            ]
        )
        request = ConvenerRequest(
            question="Should we buy a new car?",
            trigger="repeated maintenance costs",
            household_members=_MEMBERS,
        )

        composition = agent.convene(request, cycle_id="cycle-1")

        assert composition.convened_specialist_ids == ("A42", "A43", "A45")
        assert composition.convened_delegate_person_ids == (
            NodeId("person-dad"),
            NodeId("person-mum"),
            NodeId("person-elder"),
        )
        assert composition.question == request.question
        assert composition.trigger == request.trigger

        written = writer.nodes[composition.decision_id]
        assert isinstance(written, Decision)
        assert written.status == DecisionStatus.OPEN
        assert written.question == request.question
        assert written.trigger == request.trigger

    def test_duplicate_ids_are_deduplicated(self) -> None:
        agent, _writer = _agent(
            texts=[
                json.dumps(
                    {
                        "convened_specialist_ids": ["A42", "A42", "A43"],
                        "convened_delegate_person_ids": ["person-dad", "person-dad"],
                    }
                )
            ]
        )
        request = ConvenerRequest(question="q", trigger="t", household_members=_MEMBERS)

        composition = agent.convene(request, cycle_id="cycle-2")

        assert composition.convened_specialist_ids == ("A42", "A43")
        assert composition.convened_delegate_person_ids == (NodeId("person-dad"),)


class TestRejectsFabricatedIds:
    def test_unknown_specialist_id_raises(self) -> None:
        agent, _writer = _agent(
            texts=[
                json.dumps({"convened_specialist_ids": ["A99"], "convened_delegate_person_ids": []})
            ]
        )
        request = ConvenerRequest(question="q", trigger="t", household_members=_MEMBERS)

        with pytest.raises(ModelResponseMalformed):
            agent.convene(request, cycle_id="cycle-3")

    def test_unknown_delegate_person_id_raises(self) -> None:
        agent, _writer = _agent(
            texts=[
                json.dumps(
                    {
                        "convened_specialist_ids": ["A42"],
                        "convened_delegate_person_ids": ["person-does-not-exist"],
                    }
                )
            ]
        )
        request = ConvenerRequest(question="q", trigger="t", household_members=_MEMBERS)

        with pytest.raises(ModelResponseMalformed):
            agent.convene(request, cycle_id="cycle-4")

    def test_empty_specialist_ids_raises(self) -> None:
        agent, _writer = _agent(
            texts=[json.dumps({"convened_specialist_ids": [], "convened_delegate_person_ids": []})]
        )
        request = ConvenerRequest(question="q", trigger="t", household_members=_MEMBERS)

        with pytest.raises(ModelResponseMalformed):
            agent.convene(request, cycle_id="cycle-5")


class TestForbiddenHoldingAPosition:
    """A41's forbidden behaviour ("holding a position itself") is
    structurally impossible: `CouncilComposition` has no field that could
    carry a stance, reasoning-about-the-decision, or opinion of any kind —
    only participant selection and the caller's own echoed question/
    trigger."""

    def test_council_composition_has_no_stance_or_opinion_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(CouncilComposition)}
        for forbidden in ("stance", "opinion", "position", "recommendation", "verdict"):
            assert forbidden not in field_names


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _writer = _agent(texts=["{}"])
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        agent, _writer = _agent(texts=["{}"])
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)


def test_agent_id_is_a41() -> None:
    assert str(AGENT_ID) == "A41"
