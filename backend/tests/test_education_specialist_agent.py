"""Tests for A44 Education Specialist
(`app.agents.council.education_specialist_agent`).

Covers: reporting from real education-Constraint evidence, `eliminated_
branch_ids` always empty, malformed-stance/blank-reasoning rejection, and
Phase-1 isolation.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest
from contracts.graph_types import ConstraintKind, ConstraintSeverity, NodeId

from app.agents.council.education_specialist_agent import AGENT_ID, EducationSpecialistAgent
from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.types import DecisionFraming, SpecialistReportRequest
from app.graph.scoped_reader import EDUCATION_SCOPE
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, constraint, scoped
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str], nodes_by_id: dict[str, object]) -> EducationSpecialistAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id)
    return EducationSpecialistAgent(gemini_client=client, scoped_reader=scoped(reader, EDUCATION_SCOPE))


def _framing(*, related_node_ids: tuple[str, ...] = ()) -> DecisionFraming:
    branch = candidate_branch("branch-a", "Option A", "A real option", related_node_ids=related_node_ids)
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Should we move house?",
        trigger="lease renewal",
        candidate_branches=(branch,),
    )


class TestRealReporting:
    def test_reports_from_real_education_constraint_evidence(self) -> None:
        exam_year = constraint(
            "constraint-exam-year",
            kind=ConstraintKind.EDUCATION,
            severity=ConstraintSeverity.SOFT,
            original_text="Daughter is in her board-exam year",
        )
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "Moving mid board-exam year risks disrupting her catchment school.",
                        "evidence_refs": ["constraint-exam-year"],
                    }
                )
            ],
            nodes_by_id={"constraint-exam-year": exam_year},
        )
        framing = _framing(related_node_ids=("constraint-exam-year",))

        position = agent.report(SpecialistReportRequest(framing=framing))

        assert position.agent_id == "A44"
        assert position.stance == "opposes"
        assert "board-exam year" in position.reasoning
        assert position.evidence_refs == ("constraint-exam-year",)
        assert position.eliminated_branch_ids == ()


class TestNeverEliminates:
    def test_eliminated_branch_ids_always_empty(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {"stance": "supports", "reasoning": "No conflict on file.", "evidence_refs": []}
                )
            ],
            nodes_by_id={},
        )
        position = agent.report(SpecialistReportRequest(framing=_framing()))
        assert position.eliminated_branch_ids == ()


class TestMalformedResponses:
    def test_invalid_stance_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "maybe", "reasoning": "x", "evidence_refs": []})], nodes_by_id={}
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_framing()))

    def test_blank_reasoning_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "neutral", "reasoning": "", "evidence_refs": []})], nodes_by_id={}
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_framing()))


class TestPhaseOneIsolation:
    def test_report_signature_accepts_only_one_request(self) -> None:
        params = list(inspect.signature(EducationSpecialistAgent.report).parameters)
        assert params == ["self", "request"]

    def test_specialist_report_request_carries_only_framing(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SpecialistReportRequest)}
        assert field_names == {"framing"}


def test_agent_id_is_a44() -> None:
    assert str(AGENT_ID) == "A44"
