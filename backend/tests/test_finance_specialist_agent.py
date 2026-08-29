"""Tests for A42 Finance Specialist
(`app.agents.council.finance_specialist_agent`).

Covers: reporting from real Ledger-subgraph evidence, `eliminated_branch_
ids` always empty (Finance never eliminates — that is Care's exclusive
job), malformed-stance/blank-reasoning rejection, and Phase-1 isolation
(`report()` takes exactly one `SpecialistReportRequest` carrying `framing`
alone).
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest
from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId

from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.finance_specialist_agent import AGENT_ID, FinanceSpecialistAgent
from app.agents.council.types import DecisionFraming, SpecialistReportRequest
from app.graph.scoped_reader import FINANCE_SCOPE
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, ledger_event, provenance, recurring_commitment, scoped
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str], nodes_by_id: dict[str, object]) -> FinanceSpecialistAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id)
    return FinanceSpecialistAgent(gemini_client=client, scoped_reader=scoped(reader, FINANCE_SCOPE))


def _framing(*, related_node_ids: tuple[str, ...] = ()) -> DecisionFraming:
    branch = candidate_branch("branch-a", "Option A", "A real option", related_node_ids=related_node_ids)
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Buy a car?",
        trigger="repeated repairs",
        candidate_branches=(branch,),
    )


class TestRealReporting:
    def test_reports_from_real_ledger_evidence(self) -> None:
        commitment = recurring_commitment("commitment-1", label="School fees")
        event = ledger_event("event-1", amount=15000.0, counterparty_raw="Car Service Co")
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "neutral",
                        "reasoning": "Affordability is tight given the recurring school fee commitment.",
                        "evidence_refs": ["commitment-1", "event-1"],
                    }
                )
            ],
            nodes_by_id={"commitment-1": commitment, "event-1": event},
        )
        framing = _framing(related_node_ids=("commitment-1", "event-1"))

        position = agent.report(SpecialistReportRequest(framing=framing))

        assert position.agent_id == "A42"
        assert position.stance == "neutral"
        assert "recurring school fee" in position.reasoning
        assert position.evidence_refs == ("commitment-1", "event-1")
        assert position.eliminated_branch_ids == ()

    def test_out_of_scope_related_node_resolves_to_nothing(self) -> None:
        """A `Constraint` id in `related_node_ids` (Care's own scope, not
        Finance's) is invisible to this specialist's `ScopedGraphReader` —
        it never reaches the evidence block at all."""
        out_of_scope = Constraint(
            id=NodeId("constraint-out-of-scope"),
            provenance=provenance(),
            kind=ConstraintKind.MEDICAL,
            severity=ConstraintSeverity.HARD,
            validity_start=None,
            validity_end=None,
            structured={},
            original_text="Dad needs low door height",
        )
        agent = _agent(
            texts=[json.dumps({"stance": "neutral", "reasoning": "Nothing on file.", "evidence_refs": []})],
            nodes_by_id={"constraint-out-of-scope": out_of_scope},
        )
        framing = _framing(related_node_ids=("constraint-out-of-scope",))

        position = agent.report(SpecialistReportRequest(framing=framing))

        assert position.eliminated_branch_ids == ()
        assert position.stance == "neutral"


class TestNeverEliminates:
    def test_eliminated_branch_ids_always_empty(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {"stance": "opposes", "reasoning": "Too expensive right now.", "evidence_refs": []}
                )
            ],
            nodes_by_id={},
        )
        position = agent.report(SpecialistReportRequest(framing=_framing()))
        assert position.eliminated_branch_ids == ()


class TestMalformedResponses:
    def test_invalid_stance_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "undecided", "reasoning": "x", "evidence_refs": []})], nodes_by_id={}
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_framing()))

    def test_blank_reasoning_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "neutral", "reasoning": "   ", "evidence_refs": []})], nodes_by_id={}
        )
        with pytest.raises(ModelResponseMalformed):
            agent.report(SpecialistReportRequest(framing=_framing()))


class TestPhaseOneIsolation:
    def test_report_signature_accepts_only_one_request(self) -> None:
        params = list(inspect.signature(FinanceSpecialistAgent.report).parameters)
        assert params == ["self", "request"]

    def test_specialist_report_request_carries_only_framing(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SpecialistReportRequest)}
        assert field_names == {"framing"}


def test_agent_id_is_a42() -> None:
    assert str(AGENT_ID) == "A42"
