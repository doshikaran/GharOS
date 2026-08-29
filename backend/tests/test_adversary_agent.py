"""Tests for A48 Council Adversary (`app.agents.council.adversary_agent`).

Covers: the honest "no historical precedent found" path when zero real
`Outcome`s match (no Gemini call is even made), the real-citation path
(cited ids are genuinely real ids from the query result, never invented),
a malformed/fake evidence index raising (mirrors the existing index-
validation logic), and the "never proposes alternatives" forbidden
behaviour being structurally impossible.
"""

from __future__ import annotations

import dataclasses
import json

import pytest
from contracts.graph_types import NodeId

from app.agents.council.adversary_agent import _NO_PRECEDENT_CRITIQUE, AGENT_ID, CouncilAdversaryAgent
from app.agents.council.errors import ModelResponseMalformed
from app.agents.council.types import AdversaryAttack, AdversaryAttackRequest, DecisionFraming
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, outcome
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router


def _framing() -> DecisionFraming:
    branch = candidate_branch("branch-winner", "SUV", "The resolved winning option")
    return DecisionFraming(
        decision_id=NodeId("decision-1"),
        question="Buy a car?",
        trigger="repeated repairs",
        candidate_branches=(branch,),
    )


def _agent(*, models: FakeModels, reader: FakeGraphReader) -> CouncilAdversaryAgent:
    return CouncilAdversaryAgent(gemini_client=GeminiClient(router=fake_router(models)), graph_reader=reader)


def _request() -> AdversaryAttackRequest:
    return AdversaryAttackRequest(
        framing=_framing(), winning_branch_id=NodeId("branch-winner"), category_tag="major_purchase"
    )


class TestHonestNoPrecedent:
    def test_zero_real_outcomes_produces_honest_critique_and_no_model_call(self) -> None:
        reader = FakeGraphReader(nodes_by_id={}, outcome_variance_by_tag={}, history_by_entity={})
        models = FakeModels(texts=["should never be read"])
        agent = _agent(models=models, reader=reader)

        attack = agent.attack(_request())

        assert attack.cited_outcome_ids == ()
        assert attack.critique == _NO_PRECEDENT_CRITIQUE
        assert models.calls == []


class TestRealCitations:
    def test_real_outcomes_produce_real_cited_ids(self) -> None:
        outcome_a = outcome(
            "outcome-1",
            predicted="Maintenance ~₹20k/yr",
            actual="Maintenance ₹28k/yr",
            variance=0.4,
            attribution_tags=("major_purchase",),
        )
        outcome_b = outcome(
            "outcome-2",
            predicted="Resale ₹5L after 5yrs",
            actual="Resale ₹3.8L after 5yrs",
            variance=-0.24,
            attribution_tags=("major_purchase",),
        )
        reader = FakeGraphReader(
            nodes_by_id={},
            outcome_variance_by_tag={"major_purchase": (outcome_a, outcome_b)},
            history_by_entity={"branch-winner": ()},
        )
        models = FakeModels(
            texts=[
                json.dumps(
                    {
                        "critique": "This household underestimated maintenance by 40% before (outcome 0).",
                        "cited_evidence_indices": [0, 1],
                    }
                )
            ]
        )
        agent = _agent(models=models, reader=reader)

        attack = agent.attack(_request())

        assert attack.cited_outcome_ids == (NodeId("outcome-1"), NodeId("outcome-2"))
        assert attack.target_branch_id == NodeId("branch-winner")
        assert len(models.calls) == 1

    def test_fake_index_citing_nonexistent_evidence_raises(self) -> None:
        outcome_a = outcome(
            "outcome-1", predicted="p", actual="a", variance=0.1, attribution_tags=("major_purchase",)
        )
        reader = FakeGraphReader(
            nodes_by_id={},
            outcome_variance_by_tag={"major_purchase": (outcome_a,)},
            history_by_entity={"branch-winner": ()},
        )
        models = FakeModels(texts=[json.dumps({"critique": "x", "cited_evidence_indices": [5]})])
        agent = _agent(models=models, reader=reader)

        with pytest.raises(ModelResponseMalformed):
            agent.attack(_request())

    def test_real_history_available_but_no_indices_cited_raises(self) -> None:
        outcome_a = outcome(
            "outcome-1", predicted="p", actual="a", variance=0.1, attribution_tags=("major_purchase",)
        )
        reader = FakeGraphReader(
            nodes_by_id={},
            outcome_variance_by_tag={"major_purchase": (outcome_a,)},
            history_by_entity={"branch-winner": ()},
        )
        models = FakeModels(texts=[json.dumps({"critique": "x", "cited_evidence_indices": []})])
        agent = _agent(models=models, reader=reader)

        with pytest.raises(ModelResponseMalformed):
            agent.attack(_request())

    def test_blank_critique_raises(self) -> None:
        outcome_a = outcome(
            "outcome-1", predicted="p", actual="a", variance=0.1, attribution_tags=("major_purchase",)
        )
        reader = FakeGraphReader(
            nodes_by_id={},
            outcome_variance_by_tag={"major_purchase": (outcome_a,)},
            history_by_entity={"branch-winner": ()},
        )
        models = FakeModels(texts=[json.dumps({"critique": "  ", "cited_evidence_indices": [0]})])
        agent = _agent(models=models, reader=reader)

        with pytest.raises(ModelResponseMalformed):
            agent.attack(_request())


class TestForbiddenProposingAlternatives:
    def test_adversary_attack_has_no_counter_option_field(self) -> None:
        field_names = {f.name for f in dataclasses.fields(AdversaryAttack)}
        for forbidden in ("alternative", "counter_option", "proposed_option", "recommendation"):
            assert forbidden not in field_names


def test_agent_id_is_a48() -> None:
    assert str(AGENT_ID) == "A48"
