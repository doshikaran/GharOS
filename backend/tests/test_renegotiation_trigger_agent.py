"""Tests for A20 Renegotiation Trigger
(`app.agents.fair_allocator.renegotiation_trigger_agent`).

PHASES.md Phase 8's own acceptance list, this module's share of it:
- A capability flag flip is always renegotiation-worthy, deterministically
  (no model call).
- A schedule-constraint change's significance is a real Flash-tier
  judgment call, differentiated between a genuine life event and routine
  noise.
- The `CONCEDED_BY` answer: a genuine concession (computed under one
  consistent, current valuation) writes a real `Decision` + `CONCEDED_BY`
  edge; a non-concession writes nothing.

Unit tests only (fake Gemini, no network; `FakeGraphWriter` +
`InMemoryIdempotencyStore` test doubles for the T3 write path).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Decision,
    Derivation,
    EdgeType,
    NodeId,
    Provenance,
    SourceRef,
)
from contracts.tools import PermissionTier

from app.agents.fair_allocator.errors import ConcessionCostDataMissing
from app.agents.fair_allocator.renegotiation_trigger_agent import AGENT_ID, RenegotiationTriggerAgent
from app.agents.fair_allocator.types import (
    CapabilityChangeSignal,
    ConcessionCheckRequest,
    ScheduleConstraintChangeSignal,
)
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _constraint(*, structured: dict[str, str], original_text: str) -> Constraint:
    return Constraint(
        id=NodeId("constraint-1"),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-constraint-source"), region="whole-document"),
            confidence=0.9,
            deriving_agent=AgentId("A3"),
            created_at=_NOW,
        ),
        kind=ConstraintKind.SCHEDULE,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured=structured,
        original_text=original_text,
    )


def _agent(*, texts: list[str] | None = None) -> tuple[RenegotiationTriggerAgent, FakeGraphWriter]:
    fake_models = FakeModels(texts=texts or ["{}"])
    client = GeminiClient(router=fake_router(fake_models))
    writer = FakeGraphWriter()
    agent = RenegotiationTriggerAgent(
        gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
    )
    return agent, writer


class TestCapabilityChangeAlwaysTriggers:
    def test_deterministic_no_model_call(self) -> None:
        fake_models = FakeModels(texts=["should never be read"])
        agent = RenegotiationTriggerAgent(
            gemini_client=GeminiClient(router=fake_router(fake_models)),
            graph_writer=FakeGraphWriter(),
            idempotency_store=InMemoryIdempotencyStore(),
        )
        signal = CapabilityChangeSignal(
            person_id=NodeId("person-priya"), capability_name="can_drive", old_value=False, new_value=True
        )

        trigger = agent.evaluate_capability_change(signal)

        assert trigger.reason_kind == "capability_change"
        assert trigger.confidence == 1.0
        assert len(fake_models.calls) == 0


class TestScheduleChangeSignificanceJudgement:
    def test_night_shifts_is_significant(self) -> None:
        agent, _ = _agent(
            texts=[
                json.dumps(
                    {
                        "significant": True,
                        "confidence": 0.95,
                        "reasoning": "night shifts remove all evening availability, a real life event",
                    }
                )
            ]
        )
        signal = ScheduleConstraintChangeSignal(
            person_id=NodeId("person-raj"),
            new_constraint=_constraint(
                structured={"shift": "night"}, original_text="started night shifts at work"
            ),
            previous_constraint=None,
        )

        trigger = agent.evaluate_schedule_change(signal)

        assert trigger is not None
        assert trigger.reason_kind == "schedule_constraint_change"
        assert trigger.person_id == NodeId("person-raj")

    def test_minor_timing_tweak_is_not_significant(self) -> None:
        agent, _ = _agent(
            texts=[
                json.dumps(
                    {
                        "significant": False,
                        "confidence": 0.8,
                        "reasoning": "gym time moved by 10 minutes, routine and inconsequential",
                    }
                )
            ]
        )
        signal = ScheduleConstraintChangeSignal(
            person_id=NodeId("person-raj"),
            new_constraint=_constraint(structured={"activity": "gym"}, original_text="gym now at 6:40pm"),
            previous_constraint=_constraint(structured={"activity": "gym"}, original_text="gym at 6:30pm"),
        )

        trigger = agent.evaluate_schedule_change(signal)

        assert trigger is None


class TestConcessionDetection:
    def test_costlier_new_bundle_is_a_real_concession(self) -> None:
        agent, _ = _agent()
        request = ConcessionCheckRequest(
            person_id=NodeId("person-priya"),
            prior_bundle_task_ids=(NodeId("t-1"),),
            new_bundle_task_ids=(NodeId("t-2"), NodeId("t-3")),
            current_costs_for_person={"t-1": 2.0, "t-2": 5.0, "t-3": 5.0},
            renegotiation_reason="raj started night shifts",
            allocation_cycle_id="cycle-2026-09",
        )

        evidence = agent.detect_concession(request)

        assert evidence is not None
        assert evidence.prior_bundle_cost == 2.0
        assert evidence.new_bundle_cost == 10.0

    def test_no_concession_when_new_bundle_is_not_costlier(self) -> None:
        agent, _ = _agent()
        request = ConcessionCheckRequest(
            person_id=NodeId("person-priya"),
            prior_bundle_task_ids=(NodeId("t-1"), NodeId("t-2")),
            new_bundle_task_ids=(NodeId("t-1"),),
            current_costs_for_person={"t-1": 2.0, "t-2": 5.0},
            renegotiation_reason="n/a",
            allocation_cycle_id="cycle-2026-09",
        )

        evidence = agent.detect_concession(request)

        assert evidence is None

    def test_missing_cost_data_raises_rather_than_treating_as_free(self) -> None:
        agent, _ = _agent()
        request = ConcessionCheckRequest(
            person_id=NodeId("person-priya"),
            prior_bundle_task_ids=(NodeId("t-1"),),
            new_bundle_task_ids=(NodeId("t-unpriced"),),
            current_costs_for_person={"t-1": 2.0},
            renegotiation_reason="n/a",
            allocation_cycle_id="cycle-2026-09",
        )

        with pytest.raises(ConcessionCostDataMissing) as exc_info:
            agent.detect_concession(request)

        assert exc_info.value.missing_task_id == NodeId("t-unpriced")


class TestRecordConcessionWritesDecisionAndEdge:
    def test_writes_decision_and_conceded_by_edge(self) -> None:
        agent, writer = _agent()
        request = ConcessionCheckRequest(
            person_id=NodeId("person-priya"),
            prior_bundle_task_ids=(NodeId("t-1"),),
            new_bundle_task_ids=(NodeId("t-2"), NodeId("t-3")),
            current_costs_for_person={"t-1": 2.0, "t-2": 5.0, "t-3": 5.0},
            renegotiation_reason="raj started night shifts",
            allocation_cycle_id="cycle-2026-09",
        )
        evidence = agent.detect_concession(request)
        assert evidence is not None

        decision_id = agent.record_concession(evidence, allocation_cycle_id="cycle-2026-09")

        written = writer.nodes[decision_id]
        assert isinstance(written, Decision)
        assert "person-priya" in written.question
        assert written.rationale == evidence.reasoning
        conceded_by_edges = [e for e in writer.edges if e.edge_type is EdgeType.CONCEDED_BY]
        assert len(conceded_by_edges) == 1
        assert conceded_by_edges[0].from_id == decision_id
        assert conceded_by_edges[0].to_id == NodeId("person-priya")


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _ = _agent()
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        agent, _ = _agent()
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)


def test_agent_id_is_a20() -> None:
    assert str(AGENT_ID) == "A20"
