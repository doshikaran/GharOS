"""Tests for A37 Path Simulator (`app.agents.simulator.path_simulator_
agent`).

Phase 11's own acceptance list, this module's share of it:
- Real anchor resolution + `GraphReader.blast_radius_multi` seeded from
  real derived anchors; writes a real `Branch` node plus its `CONTAINS`
  edge from the `Decision`.
- **Structural proof of independence**: `simulate()` takes exactly one
  `PathSimulationRequest` and returns exactly one `BranchProjection` — two
  calls on the *same* agent instance with different/swapped fixture data
  produce fully independent results, with no leakage between them.
- Forbidden: comparing branches (no parameter through which another
  branch's data could ever reach this method) and self-assessing quality
  (`BranchProjection` has no confidence/quality field to smuggle one
  into).
- Gate 11's "every branch claim traceable to graph data": `projected_
  impacts` always carries a code-computed `"graph_blast_radius"` entry.

Unit tests only (fake Gemini, no network; `FakeGraphReader` + `FakeGraph
Writer` + `InMemoryIdempotencyStore` test doubles).
"""

from __future__ import annotations

import dataclasses
import inspect
import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    AgentId,
    Branch,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Derivation,
    EdgeType,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Person,
    PersonRole,
    Provenance,
)
from contracts.tools import PermissionTier

from app.agents.simulator.errors import ModelResponseMalformed
from app.agents.simulator.path_simulator_agent import AGENT_ID, PathSimulatorAgent
from app.agents.simulator.types import BranchProjection, GroundingResult, PathSimulationRequest
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient, GroundedCitation
from app.tools.errors import GatedToolRegistrationDenied

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_reader import FakeGraphReader
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _provenance() -> Provenance:
    # AMBIGUOUS/no source_ref — these fixtures stand in for real household
    # entities already on the graph; only EXTRACTED/INFERRED provenance
    # requires a real SourceRef (contracts.graph_types.Provenance).
    return Provenance(
        derivation=Derivation.AMBIGUOUS,
        source_ref=None,
        confidence=0.9,
        deriving_agent=AgentId("A3"),
        created_at=_NOW,
    )


def _person(node_id: str, name: str) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=_provenance(),
        display_name=name,
        aliases=(),
        role=PersonRole.ELDER,
        can_drive=False,
        can_sign=True,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=LanguageProfile(
            primary_language="en",
            languages_understood=("en",),
            script_preference="latin",
            code_mixing_profile=None,
            formality_preference=None,
            literacy_mode=LiteracyMode.TEXT_CAPABLE,
        ),
    )


def _obligation(node_id: str, title: str) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=_provenance(),
        title=title,
        obligation_type="school",
        due_at=None,
        must_start_by=None,
        effort_estimate_minutes=None,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _constraint(node_id: str, original_text: str) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=_provenance(),
        kind=ConstraintKind.SCHEDULE,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={},
        original_text=original_text,
    )


def _agent(
    *,
    texts: list[str],
    nodes_by_id: dict[str, object],
    blast_radius_multi_by_ids: dict[tuple[str, ...], tuple[object, ...]],
) -> tuple[PathSimulatorAgent, FakeGraphReader, FakeGraphWriter]:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id, blast_radius_multi_by_ids=blast_radius_multi_by_ids)
    writer = FakeGraphWriter()
    agent = PathSimulatorAgent(
        gemini_client=client,
        graph_reader=reader,
        graph_writer=writer,
        idempotency_store=InMemoryIdempotencyStore(),
    )
    return agent, reader, writer


class TestRealAnchorsAndBlastRadius:
    def test_projection_carries_real_blast_radius_and_writes_branch(self) -> None:
        priya_mother = _person("person-priya-mother", "Priya's mother")
        stale_id = "person-does-not-exist"
        real_anchor_ids = (NodeId("person-priya-mother"),)
        agent, reader, writer = _agent(
            texts=[
                json.dumps(
                    {
                        "projected_impacts": {
                            "care_continuity": "Grandma stays near her existing dialysis clinic."
                        }
                    }
                )
            ],
            nodes_by_id={"person-priya-mother": priya_mother},
            blast_radius_multi_by_ids={real_anchor_ids: (priya_mother,)},
        )
        request = PathSimulationRequest(
            decision_id=NodeId("decision-1"),
            branch_label="stay_in_mumbai",
            branch_topic="staying in Mumbai near existing elder care",
            candidate_anchor_ids=(NodeId("person-priya-mother"), NodeId(stale_id)),
            grounding=None,
        )

        projection = agent.simulate(request, cycle_id="cycle-1")

        # The stale candidate id never resolved, so it never reached blast_radius_multi.
        assert reader.blast_radius_multi_calls == [(real_anchor_ids, 2)]
        assert projection.blast_radius_node_ids == (NodeId("person-priya-mother"),)
        assert "graph_blast_radius" in projection.projected_impacts
        assert "1 real household entities" in projection.projected_impacts["graph_blast_radius"]
        assert "Priya's mother" in projection.projected_impacts["graph_blast_radius"]
        assert (
            projection.projected_impacts["care_continuity"]
            == "Grandma stays near her existing dialysis clinic."
        )

        written = writer.nodes[projection.branch_id]
        assert isinstance(written, Branch)
        assert written.decision_id == NodeId("decision-1")
        assert written.label == "stay_in_mumbai"
        contains_edges = [e for e in writer.edges if e.edge_type is EdgeType.CONTAINS]
        assert len(contains_edges) == 1
        assert contains_edges[0].from_id == NodeId("decision-1")
        assert contains_edges[0].to_id == projection.branch_id

    def test_grounding_refs_are_formatted_from_real_citations(self) -> None:
        agent, _reader, _writer = _agent(
            texts=[json.dumps({"projected_impacts": {}})],
            nodes_by_id={},
            blast_radius_multi_by_ids={(): ()},
        )
        citation = GroundedCitation(
            title="Bangalore Cost of Living 2026",
            uri="https://example.com/col",
            retrieved_at=datetime(2026, 8, 20, 9, 0, tzinfo=UTC),
        )
        grounding = GroundingResult(
            branch_label="move_to_bangalore",
            citations=(citation,),
            summary="Rents rose 8% year over year.",
            freshness_note="Published within the last six months.",
        )
        request = PathSimulationRequest(
            decision_id=NodeId("decision-1"),
            branch_label="move_to_bangalore",
            branch_topic="relocating to Bangalore",
            candidate_anchor_ids=(),
            grounding=grounding,
        )

        projection = agent.simulate(request, cycle_id="cycle-2")

        assert len(projection.grounding_refs) == 1
        assert projection.grounding_refs[0] == (
            "Bangalore Cost of Living 2026 (https://example.com/col) — retrieved 2026-08-20T09:00:00+00:00"
        )

    def test_non_string_projected_impact_value_is_rejected(self) -> None:
        agent, _reader, _writer = _agent(
            texts=[json.dumps({"projected_impacts": {"cost": 42}})],
            nodes_by_id={},
            blast_radius_multi_by_ids={(): ()},
        )
        request = PathSimulationRequest(
            decision_id=NodeId("decision-1"),
            branch_label="branch",
            branch_topic="topic",
            candidate_anchor_ids=(),
            grounding=None,
        )

        with pytest.raises(ModelResponseMalformed):
            agent.simulate(request, cycle_id="cycle-3")


class TestGenuineIndependence:
    """Two calls on the *same* `PathSimulatorAgent` instance, with
    different/swapped fixture data, produce fully independent
    `BranchProjection`s — no field on `PathSimulationRequest` can carry
    another branch's data, and this agent holds no per-call mutable state
    (see module docstring)."""

    def test_two_calls_with_swapped_fixture_data_never_leak_into_each_other(self) -> None:
        priya_mother = _person("person-priya-mother", "Priya's mother")
        board_exam = _constraint("constraint-board-exam", "daughter is in her board-exam year")
        school_fee = _obligation("obligation-school-fee", "school fee due")

        anchors_a = (NodeId("person-priya-mother"),)
        anchors_b = (NodeId("constraint-board-exam"), NodeId("obligation-school-fee"))

        fake_models = FakeModels(
            texts=[
                json.dumps({"projected_impacts": {"care": "stays near dialysis clinic"}}),
                json.dumps({"projected_impacts": {"school": "daughter changes schools mid board-exam year"}}),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        reader = FakeGraphReader(
            nodes_by_id={
                "person-priya-mother": priya_mother,
                "constraint-board-exam": board_exam,
                "obligation-school-fee": school_fee,
            },
            blast_radius_multi_by_ids={
                anchors_a: (priya_mother,),
                anchors_b: (board_exam, school_fee),
            },
        )
        writer = FakeGraphWriter()
        agent = PathSimulatorAgent(
            gemini_client=client,
            graph_reader=reader,
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
        )

        request_a = PathSimulationRequest(
            decision_id=NodeId("decision-1"),
            branch_label="stay_in_mumbai",
            branch_topic="staying in Mumbai",
            candidate_anchor_ids=anchors_a,
            grounding=None,
        )
        request_b = PathSimulationRequest(
            decision_id=NodeId("decision-1"),
            branch_label="move_to_bangalore",
            branch_topic="relocating to Bangalore",
            candidate_anchor_ids=anchors_b,
            grounding=None,
        )

        projection_a = agent.simulate(request_a, cycle_id="cycle-a")
        projection_b = agent.simulate(request_b, cycle_id="cycle-b")

        assert projection_a.branch_id != projection_b.branch_id
        assert projection_a.label == "stay_in_mumbai"
        assert projection_b.label == "move_to_bangalore"
        assert projection_a.blast_radius_node_ids == (NodeId("person-priya-mother"),)
        assert projection_b.blast_radius_node_ids == (
            NodeId("constraint-board-exam"),
            NodeId("obligation-school-fee"),
        )
        # Disjoint blast radii — no leakage in either direction.
        assert set(projection_a.blast_radius_node_ids).isdisjoint(projection_b.blast_radius_node_ids)
        assert "care" in projection_a.projected_impacts
        assert "care" not in projection_b.projected_impacts
        assert "school" in projection_b.projected_impacts
        assert "school" not in projection_a.projected_impacts
        assert (
            projection_a.projected_impacts["graph_blast_radius"]
            != (projection_b.projected_impacts["graph_blast_radius"])
        )
        # Two real, independently-seeded reads — never one call answering for both.
        assert reader.blast_radius_multi_calls == [(anchors_a, 2), (anchors_b, 2)]


class TestForbiddenComparingBranches:
    def test_simulate_signature_accepts_only_one_branchs_own_request(self) -> None:
        params = list(inspect.signature(PathSimulatorAgent.simulate).parameters)
        assert params == ["self", "request", "cycle_id"]

    def test_path_simulation_request_carries_no_sibling_branch_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(PathSimulationRequest)}
        forbidden_substrings = ("branches", "sibling", "other_branch", "compare")
        for name in field_names:
            for forbidden in forbidden_substrings:
                assert forbidden not in name.lower()


class TestForbiddenSelfAssessingQuality:
    def test_branch_projection_has_no_confidence_or_quality_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(BranchProjection)}
        for forbidden in ("confidence", "quality", "self_rating", "score"):
            assert forbidden not in field_names


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _reader, _writer = _agent(texts=["{}"], nodes_by_id={}, blast_radius_multi_by_ids={})
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        agent, _reader, _writer = _agent(texts=["{}"], nodes_by_id={}, blast_radius_multi_by_ids={})
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)


def test_agent_id_is_a37() -> None:
    assert str(AGENT_ID) == "A37"
