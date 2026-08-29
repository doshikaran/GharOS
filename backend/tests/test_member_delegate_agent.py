"""Tests for A47 Member Delegate (`app.agents.council.member_delegate_agent`).

Covers: sparse-by-omission cost extraction (never a fabricated `0.0` for a
genuinely-unknown cost), the confidence floor, invented-branch-id
rejection, the structural "cannot speak for anyone else" guarantee
(constructor takes exactly one `person_id`; `DelegateScoringRequest` has
no `person_id` field at all), blank-reasoning rejection, and Phase-1
isolation.
"""

from __future__ import annotations

import dataclasses
import inspect
import json

import pytest
from contracts.graph_types import NodeId

from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.member_delegate_agent import AGENT_ID, MemberDelegateAgent
from app.agents.council.types import DecisionFraming, DelegateScoringRequest
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch
from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str], person_id: str = "person-dad") -> MemberDelegateAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return MemberDelegateAgent(gemini_client=client, person_id=NodeId(person_id))


def _framing() -> DecisionFraming:
    branch_a = candidate_branch("branch-a", "Hatchback", "Compact, cheap to run")
    branch_b = candidate_branch("branch-b", "SUV", "Roomy, expensive to run")
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Buy a car?",
        trigger="repeated repairs",
        candidate_branches=(branch_a, branch_b),
    )


def _request() -> DelegateScoringRequest:
    return DelegateScoringRequest(framing=_framing(), known_preference_signals=(), elicitation_method="mixed")


class TestSparseByOmission:
    def test_a_genuinely_unknown_cost_is_absent_never_zero(self) -> None:
        """The model only returns a priced entry for branch-a — branch-b
        must be absent from `costs`, never fabricated as `0.0`."""
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "reasoning": "Only confident about the hatchback's running cost.",
                        "branch_costs": [{"branch_id": "branch-a", "cost": 10.0, "confidence": 0.9}],
                    }
                )
            ]
        )
        scoring = agent.score(_request())

        assert scoring.valuation_profile.costs == {"branch-a": 10.0}
        assert "branch-b" not in scoring.valuation_profile.costs

    def test_low_confidence_cost_is_dropped_not_written(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "reasoning": "Not sure about branch-b's real cost to me.",
                        "branch_costs": [
                            {"branch_id": "branch-a", "cost": 10.0, "confidence": 0.9},
                            {"branch_id": "branch-b", "cost": 5.0, "confidence": 0.2},
                        ],
                    }
                )
            ]
        )
        scoring = agent.score(_request())

        assert scoring.valuation_profile.costs == {"branch-a": 10.0}

    def test_invented_branch_id_is_dropped_never_propagated(self) -> None:
        agent = _agent(
            texts=[
                json.dumps(
                    {
                        "reasoning": "x",
                        "branch_costs": [
                            {"branch_id": "branch-does-not-exist", "cost": 5.0, "confidence": 1.0}
                        ],
                    }
                )
            ]
        )
        scoring = agent.score(_request())

        assert scoring.valuation_profile.costs == {}


class TestNeverSpeaksForAnyoneElse:
    """spec §15.9 A47 forbidden: "speaking for anyone else." Structurally
    enforced: the constructor takes exactly one `person_id`, and
    `DelegateScoringRequest` has no field through which a caller could ask
    this instance to score on behalf of a different person."""

    def test_constructor_takes_exactly_one_person_id_keyword(self) -> None:
        params = inspect.signature(MemberDelegateAgent.__init__).parameters
        assert set(params) == {"self", "gemini_client", "person_id"}

    def test_delegate_scoring_request_has_no_person_id_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(DelegateScoringRequest)}
        assert "person_id" not in field_names

    def test_every_produced_scoring_carries_the_bound_person_id(self) -> None:
        agent = _agent(texts=[json.dumps({"reasoning": "x", "branch_costs": []})], person_id="person-mum")
        scoring = agent.score(_request())
        assert scoring.person_id == NodeId("person-mum")
        assert scoring.valuation_profile.person_id == NodeId("person-mum")
        assert agent.person_id == NodeId("person-mum")


class TestMalformedResponses:
    def test_blank_reasoning_raises(self) -> None:
        agent = _agent(texts=[json.dumps({"reasoning": "  ", "branch_costs": []})])
        with pytest.raises(ModelResponseMalformed):
            agent.score(
                DelegateScoringRequest(
                    framing=_framing(), known_preference_signals=(), elicitation_method="mixed"
                )
            )


class TestPhaseOneIsolation:
    def test_score_signature_accepts_only_one_request(self) -> None:
        params = list(inspect.signature(MemberDelegateAgent.score).parameters)
        assert params == ["self", "request"]

    def test_delegate_scoring_request_carries_no_sibling_output_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(DelegateScoringRequest)}
        forbidden_substrings = ("position", "specialist", "sibling", "other_delegate", "delegate_scorings")
        for name in field_names:
            for forbidden in forbidden_substrings:
                assert forbidden not in name.lower()


def test_agent_id_is_a47() -> None:
    assert str(AGENT_ID) == "A47"
