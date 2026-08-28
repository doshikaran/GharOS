"""Tests for A35 Decision Framing (`app.agents.simulator.decision_framing_
agent`).

Phase 11's own acceptance list, this module's share of it:
- False-binary detection and unconsidered-option surfacing are real
  Pro-tier judgment calls, parsed and surfaced unchanged onto
  `types.DecisionFrame`.
- A model "unconsidered option" that merely restates an already-proposed
  branch label is rejected, never silently accepted as if it were genuine.
- Forward-mode `frame()` writes a real `status=OPEN` `Decision` node via
  the T3 write path — verified against a real in-memory `FakeGraphWriter`,
  not a mock that only records calls.
- Backward-mode `frame_backward()` is deterministic (no model call at all)
  and structurally empty on its fork-shaped fields.

Unit tests only (fake Gemini, no network; `FakeGraphWriter` +
`InMemoryIdempotencyStore` test doubles for the T3 write path — the same
construction pattern `test_renegotiation_trigger_agent.py` established for
an identically-shaped writer agent).
"""

from __future__ import annotations

import json

import pytest
from contracts.graph_types import Decision, DecisionStatus
from contracts.tools import PermissionTier

from app.agents.simulator.decision_framing_agent import AGENT_ID, DecisionFramingAgent
from app.agents.simulator.errors import ModelResponseMalformed
from app.agents.simulator.types import BackwardFramingRequest, DecisionFramingRequest
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router


def _agent(texts: list[str] | None = None) -> tuple[DecisionFramingAgent, FakeGraphWriter]:
    fake_models = FakeModels(texts=texts or ["{}"])
    client = GeminiClient(router=fake_router(fake_models))
    writer = FakeGraphWriter()
    agent = DecisionFramingAgent(
        gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
    )
    return agent, writer


def _forward_request(**overrides: object) -> DecisionFramingRequest:
    defaults: dict[str, object] = {
        "household_request_text": "Should we move to Bangalore or stay in Mumbai?",
        "trigger": "Raj's company offered a Bangalore relocation package",
        "proposed_branch_labels": ("move_to_bangalore", "stay_in_mumbai"),
        "known_household_context": (
            "Priya's mother (elder) lives 10 minutes away in Mumbai and has twice-weekly dialysis.",
            "Their daughter is in her board-exam year (10th standard) this academic year.",
        ),
    }
    defaults.update(overrides)
    return DecisionFramingRequest(**defaults)  # type: ignore[arg-type]


class TestFalseBinaryDetectionAndUnconsideredOptions:
    def test_detects_false_binary_and_surfaces_unconsidered_option(self) -> None:
        response = json.dumps(
            {
                "question": "Should the household relocate to Bangalore or remain in Mumbai?",
                "is_false_binary": True,
                "unconsidered_options": [
                    "A hybrid arrangement: Raj works remotely from Mumbai three weeks a month "
                    "and travels to Bangalore for the fourth, avoiding a full relocation during "
                    "the board-exam year."
                ],
            }
        )
        agent, writer = _agent(texts=[response])

        frame = agent.frame(_forward_request(), cycle_id="cycle-2026-09")

        assert frame.is_false_binary is True
        assert len(frame.unconsidered_options) == 1
        assert "hybrid" in frame.unconsidered_options[0].lower()
        assert frame.proposed_branch_labels == ("move_to_bangalore", "stay_in_mumbai")
        assert frame.trigger == "Raj's company offered a Bangalore relocation package"

        written = writer.nodes[frame.decision_id]
        assert isinstance(written, Decision)
        assert written.status is DecisionStatus.OPEN
        assert written.question == frame.question

    def test_no_false_binary_is_surfaced_plainly(self) -> None:
        response = json.dumps(
            {
                "question": "Should we hire a night nurse for Grandma?",
                "is_false_binary": False,
                "unconsidered_options": [],
            }
        )
        agent, _writer = _agent(texts=[response])

        frame = agent.frame(_forward_request(), cycle_id="cycle-2026-09")

        assert frame.is_false_binary is False
        assert frame.unconsidered_options == ()

    def test_unconsidered_option_restating_a_proposed_label_is_rejected(self) -> None:
        response = json.dumps(
            {
                "question": "Should the household relocate to Bangalore or remain in Mumbai?",
                "is_false_binary": True,
                # Case/whitespace-insensitive restatement of a real proposed label.
                "unconsidered_options": ["  Move_To_Bangalore  "],
            }
        )
        agent, _writer = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed) as exc_info:
            agent.frame(_forward_request(), cycle_id="cycle-2026-09")

        assert "restates an already-proposed" in str(exc_info.value)

    def test_blank_question_is_rejected(self) -> None:
        response = json.dumps({"question": "   ", "is_false_binary": False, "unconsidered_options": []})
        agent, _writer = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.frame(_forward_request(), cycle_id="cycle-2026-09")


class TestForwardModeWritesARealDecisionNode:
    def test_decision_node_has_open_status_and_ambiguous_provenance(self) -> None:
        response = json.dumps(
            {"question": "Should we relocate?", "is_false_binary": False, "unconsidered_options": []}
        )
        agent, writer = _agent(texts=[response])

        frame = agent.frame(_forward_request(), cycle_id="cycle-42")

        assert writer.write_node_calls == 1
        written = writer.nodes[frame.decision_id]
        assert isinstance(written, Decision)
        assert written.status is DecisionStatus.OPEN
        assert written.trigger == "Raj's company offered a Bangalore relocation package"
        assert written.provenance.deriving_agent == AGENT_ID
        assert written.provenance.confidence == 1.0

    def test_replaying_the_same_cycle_id_never_double_writes(self) -> None:
        response = json.dumps(
            {"question": "Should we relocate?", "is_false_binary": False, "unconsidered_options": []}
        )
        agent, writer = _agent(texts=[response, response])

        first = agent.frame(_forward_request(), cycle_id="cycle-idempotent")
        second = agent.frame(_forward_request(), cycle_id="cycle-idempotent")

        assert first.decision_id == second.decision_id
        assert writer.write_node_calls == 1


class TestBackwardModeIsDeterministic:
    def test_no_model_call_and_structurally_empty_fork_fields(self) -> None:
        fake_models = FakeModels(texts=["should never be read"])
        client = GeminiClient(router=fake_router(fake_models))
        writer = FakeGraphWriter()
        agent = DecisionFramingAgent(
            gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
        )
        request = BackwardFramingRequest(
            plan_description="We relocated the household to Bangalore in June 2026",
            category_tag="relocation",
        )

        frame = agent.frame_backward(request, cycle_id="cycle-backward-1")

        assert len(fake_models.calls) == 0
        assert frame.is_false_binary is False
        assert frame.unconsidered_options == ()
        assert frame.proposed_branch_labels == ()
        assert "We relocated the household to Bangalore in June 2026" in frame.question
        assert "relocation" in frame.trigger

    def test_writes_a_real_open_decision_node(self) -> None:
        fake_models = FakeModels(texts=["should never be read"])
        client = GeminiClient(router=fake_router(fake_models))
        writer = FakeGraphWriter()
        agent = DecisionFramingAgent(
            gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
        )
        request = BackwardFramingRequest(
            plan_description="We signed a two-year lease on the new apartment",
            category_tag="major_purchase",
        )

        frame = agent.frame_backward(request, cycle_id="cycle-backward-2")

        written = writer.nodes[frame.decision_id]
        assert isinstance(written, Decision)
        assert written.status is DecisionStatus.OPEN


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _writer = _agent()
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        agent, _writer = _agent()
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)


def test_agent_id_is_a35() -> None:
    assert str(AGENT_ID) == "A35"
