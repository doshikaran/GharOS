"""Tests for A43 Care Specialist (`app.agents.council.care_specialist_agent`).

This is the one specialist whose `SpecialistPosition.eliminated_branch_ids`
can ever be non-empty (Gate 12: "Care's hard constraint ELIMINATES options,
does not score them down"). Covers the concrete elimination fixture
(spec §12.4's own worked example: a HARD mobility constraint ruling out a
real branch), the real code-level gate that a HARD constraint must
genuinely be on file before any elimination is even honoured, invented
branch-id rejection, and the same malformed-response/isolation coverage
every specialist gets.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest
from contracts.graph_types import ConstraintKind, ConstraintSeverity, NodeId

from app.agents.council.care_specialist_agent import AGENT_ID, CareSpecialistAgent
from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.types import DecisionFraming, SpecialistReportRequest
from app.graph.scoped_reader import CARE_SCOPE
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, constraint, scoped
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str], nodes_by_id: dict[str, object]) -> CareSpecialistAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id)
    return CareSpecialistAgent(gemini_client=client, scoped_reader=scoped(reader, CARE_SCOPE))


def _two_branch_framing(*, related_node_ids: tuple[str, ...] = ()) -> DecisionFraming:
    low_door = candidate_branch(
        "branch-low-door-hatchback",
        "Compact hatchback",
        "Low door sill, 38cm",
        related_node_ids=related_node_ids,
    )
    high_door = candidate_branch(
        "branch-high-door-suv",
        "SUV",
        "High door sill, 55cm — dad's mobility constraint rules this out",
        related_node_ids=related_node_ids,
    )
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Buy a car?",
        trigger="repeated repairs",
        candidate_branches=(low_door, high_door),
    )


class TestRealHardConstraintElimination:
    """spec §12.4's own worked example: "Dad's mobility constraint sets
    minimum door height and maximum seat height. Hard constraint —
    eliminates options.\""""

    def test_real_hard_mobility_constraint_eliminates_the_real_branch_it_rules_out(self) -> None:
        mobility_constraint = constraint(
            "constraint-dad-mobility",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.HARD,
            original_text="Dad cannot step up more than 45cm to enter a vehicle",
            structured={"max_door_sill_cm": "45"},
        )
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "The SUV's 55cm door sill exceeds Dad's real mobility constraint.",
                        "evidence_refs": ["constraint-dad-mobility"],
                        "hard_eliminations": [
                            {"branch_id": "branch-high-door-suv", "reason": "exceeds max door sill height"}
                        ],
                    }
                )
            ],
            nodes_by_id={"constraint-dad-mobility": mobility_constraint},
        )
        framing = _two_branch_framing(related_node_ids=("constraint-dad-mobility",))

        position = agent.report(SpecialistReportRequest(framing=framing))

        assert position.agent_id == "A43"
        assert position.eliminated_branch_ids == (NodeId("branch-high-door-suv"),)
        assert "mobility constraint" in position.reasoning


class TestNoHardConstraintNoElimination:
    def test_no_hard_constraint_on_file_means_nothing_is_eliminated(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "supports",
                        "reasoning": "No mobility issue on file.",
                        "evidence_refs": [],
                        "hard_eliminations": [],
                    }
                )
            ],
            nodes_by_id={},
        )
        position = agent.report(SpecialistReportRequest(framing=_two_branch_framing()))
        assert position.eliminated_branch_ids == ()

    def test_model_volunteering_elimination_with_no_real_hard_constraint_is_rejected(self) -> None:
        """The real, code-level gate: the model cannot conjure an
        elimination when this specialist's own scope found no real HARD
        constraint to justify one — a malformed response, never honoured."""
        soft_constraint = constraint(
            "constraint-soft-preference",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.SOFT,
            original_text="Dad finds high seats slightly less comfortable",
        )
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "x",
                        "evidence_refs": [],
                        "hard_eliminations": [{"branch_id": "branch-high-door-suv", "reason": "discomfort"}],
                    }
                )
            ],
            nodes_by_id={"constraint-soft-preference": soft_constraint},
        )
        framing = _two_branch_framing(related_node_ids=("constraint-soft-preference",))

        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=framing))


class TestInventedBranchIdRejected:
    def test_eliminating_a_branch_id_outside_the_real_candidate_set_raises(self) -> None:
        mobility_constraint = constraint(
            "constraint-dad-mobility",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.HARD,
            original_text="Dad cannot step up more than 45cm",
        )
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "x",
                        "evidence_refs": [],
                        "hard_eliminations": [{"branch_id": "branch-does-not-exist", "reason": "y"}],
                    }
                )
            ],
            nodes_by_id={"constraint-dad-mobility": mobility_constraint},
        )
        framing = _two_branch_framing(related_node_ids=("constraint-dad-mobility",))

        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=framing))


class TestMalformedResponses:
    def test_invalid_stance_raises(self) -> None:
        agent = _agent(
            texts=[
                json.dumps({"stance": "sure", "reasoning": "x", "evidence_refs": [], "hard_eliminations": []})
            ],
            nodes_by_id={},
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_two_branch_framing()))

    def test_blank_reasoning_raises(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {"stance": "neutral", "reasoning": " ", "evidence_refs": [], "hard_eliminations": []}
                )
            ],
            nodes_by_id={},
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_two_branch_framing()))


class TestPhaseOneIsolation:
    def test_report_signature_accepts_only_one_request(self) -> None:
        params = list(inspect.signature(CareSpecialistAgent.report).parameters)
        assert params == ["self", "request"]

    def test_specialist_report_request_carries_only_framing(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SpecialistReportRequest)}
        assert field_names == {"framing"}


def test_agent_id_is_a43() -> None:
    assert str(AGENT_ID) == "A43"
