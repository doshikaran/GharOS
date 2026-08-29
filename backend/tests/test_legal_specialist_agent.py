"""Tests for A46 Legal/Compliance Specialist
(`app.agents.council.legal_specialist_agent`).

Covers: reporting from real legal/custody-Constraint and SourceDocument
evidence, `eliminated_branch_ids` always empty, malformed-stance/blank-
reasoning rejection, Phase-1 isolation, and the "never give legal advice"
forbidden behaviour — enforced by prompt instruction, checked here by a
real text-pattern assertion against the loaded prompt (spec §15.9 A46's
own forbidden list).
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest
from contracts.graph_types import ConstraintKind, ConstraintSeverity, NodeId

from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.legal_specialist_agent import AGENT_ID, LegalSpecialistAgent
from app.agents.council.types import DecisionFraming, SpecialistReportRequest
from app.graph.scoped_reader import LEGAL_SCOPE
from app.prompts.loader import load_prompt
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, constraint, scoped, source_document
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str], nodes_by_id: dict[str, object]) -> LegalSpecialistAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id)
    return LegalSpecialistAgent(gemini_client=client, scoped_reader=scoped(reader, LEGAL_SCOPE))


def _framing(*, related_node_ids: tuple[str, ...] = ()) -> DecisionFraming:
    branch = candidate_branch("branch-a", "Option A", "A real option", related_node_ids=related_node_ids)
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Should we move house?",
        trigger="lease renewal",
        candidate_branches=(branch,),
    )


class TestRealReporting:
    def test_reports_from_real_legal_evidence(self) -> None:
        society_rules = source_document("doc-society-rules", document_type="society_notice")
        custody_clause = constraint(
            "constraint-custody",
            kind=ConstraintKind.CUSTODY,
            severity=ConstraintSeverity.HARD,
            original_text="Shared custody requires notice before relocation",
        )
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "stance": "neutral",
                        "reasoning": "The custody clause requires notice; flag for a family lawyer.",
                        "evidence_refs": ["doc-society-rules", "constraint-custody"],
                    }
                )
            ],
            nodes_by_id={"doc-society-rules": society_rules, "constraint-custody": custody_clause},
        )
        framing = _framing(related_node_ids=("doc-society-rules", "constraint-custody"))

        position = agent.report(SpecialistReportRequest(framing=framing))

        assert position.agent_id == "A46"
        assert "family lawyer" in position.reasoning
        assert position.evidence_refs == ("doc-society-rules", "constraint-custody")
        assert position.eliminated_branch_ids == ()


class TestNeverEliminates:
    def test_eliminated_branch_ids_always_empty(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {"stance": "neutral", "reasoning": "No documentation gap found.", "evidence_refs": []}
                )
            ],
            nodes_by_id={},
        )
        position = agent.report(SpecialistReportRequest(framing=_framing()))
        assert position.eliminated_branch_ids == ()


class TestNeverGivesLegalAdvice:
    """spec §15.9 A46's own forbidden behaviour: "giving legal advice —
    flags issues for professional review." Enforced by prompt instruction
    (this module holds no tool of any kind that could constitute "advice"
    as an action, only a reported position) — checked here directly
    against the real, loaded prompt text."""

    def test_prompt_explicitly_instructs_against_giving_legal_advice(self) -> None:
        prompt_text = load_prompt("A46").text.lower()
        assert "never give legal advice" in prompt_text
        assert "professional review" in prompt_text


class TestMalformedResponses:
    def test_invalid_stance_raises(self) -> None:
        agent = _agent(
            texts=[json.dumps({"stance": "undecided", "reasoning": "x", "evidence_refs": []})], nodes_by_id={}
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
        params = list(inspect.signature(LegalSpecialistAgent.report).parameters)
        assert params == ["self", "request"]

    def test_specialist_report_request_carries_only_framing(self) -> None:
        field_names = {f.name for f in dataclasses.fields(SpecialistReportRequest)}
        assert field_names == {"framing"}


def test_agent_id_is_a46() -> None:
    assert str(AGENT_ID) == "A46"
