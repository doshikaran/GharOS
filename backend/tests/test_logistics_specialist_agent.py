"""Tests for A45 Logistics Specialist
(`app.agents.council.logistics_specialist_agent`).

Covers: reporting from real Obligation-subgraph evidence, `eliminated_
branch_ids` always empty, malformed-stance/blank-reasoning rejection, and
Phase-1 isolation.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest
from contracts.graph_types import NodeId

from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.logistics_specialist_agent import AGENT_ID, LogisticsSpecialistAgent
from app.agents.council.types import DecisionFraming, SpecialistReportRequest
from app.graph.scoped_reader import LOGISTICS_SCOPE
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, obligation, scoped
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str], nodes_by_id: dict[str, object]) -> LogisticsSpecialistAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id)
    return LogisticsSpecialistAgent(gemini_client=client, scoped_reader=scoped(reader, LOGISTICS_SCOPE))


def _framing(*, related_node_ids: tuple[str, ...] = ()) -> DecisionFraming:
    branch = candidate_branch("branch-a", "Option A", "A real option", related_node_ids=related_node_ids)
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Buy a car?",
        trigger="repeated repairs",
        candidate_branches=(branch,),
    )


class TestRealReporting:
    def test_reports_from_real_obligation_evidence(self) -> None:
        school_run = obligation("obligation-school-run", "School run", obligation_type="school")
        dialysis_trip = obligation("obligation-dialysis", "Dialysis trip", obligation_type="medical")
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "supports",
                        "reasoning": "The school run and dialysis trip both need real boot space.",
                        "evidence_refs": ["obligation-school-run", "obligation-dialysis"],
                    }
                )
            ],
            nodes_by_id={"obligation-school-run": school_run, "obligation-dialysis": dialysis_trip},
        )
        framing = _framing(related_node_ids=("obligation-school-run", "obligation-dialysis"))

        position = agent.report(SpecialistReportRequest(framing=framing))

        assert position.agent_id == "A45"
        assert position.stance == "supports"
        assert "dialysis trip" in position.reasoning
        assert position.evidence_refs == ("obligation-school-run", "obligation-dialysis")
        assert position.eliminated_branch_ids == ()


class TestNeverEliminates:
    def test_eliminated_branch_ids_always_empty(self) -> None:
        agent = _agent(
            texts=[
                json.dumps({"stance": "neutral", "reasoning": "No conflict on file.", "evidence_refs": []})
            ],
            nodes_by_id={},
        )
        position = agent.report(SpecialistReportRequest(framing=_framing()))
        assert position.eliminated_branch_ids == ()


class TestMalformedResponses:
    def test_invalid_stance_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "unsure", "reasoning": "x", "evidence_refs": []})], nodes_by_id={}
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_framing()))

    def test_blank_reasoning_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "neutral", "reasoning": "  ", "evidence_refs": []})], nodes_by_id={}
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_framing()))


class TestPhaseOneIsolation:
    def test_report_signature_accepts_only_one_request(self) -> None:
        params = list(inspect.signature(LogisticsSpecialistAgent.report).parameters)
        assert params == ["self", "request"]

    def test_specialist_report_request_carries_only_framing(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SpecialistReportRequest)}
        assert field_names == {"framing"}


def test_agent_id_is_a45() -> None:
    assert str(AGENT_ID) == "A45"
