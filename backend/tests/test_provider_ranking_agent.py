"""Tests for A52 Provider Ranking
(`app.agents.concierge.provider_ranking_agent`).

The rank order/reasons/demotion logic itself is covered exhaustively,
without any Gemini mocking, in `test_ranking.py` — these tests cover the
agent wrapper: that the deterministic order survives the narrative call
untouched, that the model cannot reorder anything (forbidden: opaque
ranking), and the empty-candidates cost-discipline short-circuit.
"""

from __future__ import annotations

import json

from contracts.graph_types import NodeId

from app.agents.concierge.provider_ranking_agent import AGENT_ID, ProviderRankingAgent
from app.agents.concierge.types import ProviderCandidate, RankingContext, UrgencyLevel
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(texts: list[str] | None = None) -> ProviderRankingAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return ProviderRankingAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _candidate(provider_id: str, *, rating: float, distance_km: float) -> ProviderCandidate:
    return ProviderCandidate(
        provider_id=NodeId(provider_id),
        name=f"Clinic {provider_id}",
        category="dental",
        rating=rating,
        distance_km=distance_km,
        availability_notes=None,
        price_band="$$",
        specialisations=(),
        is_existing_household_provider=False,
    )


def _context() -> RankingContext:
    return RankingContext(
        urgency=UrgencyLevel.ROUTINE, provider_earliest_offset_days={}, reliability_by_provider={}
    )


class TestNarrativeNeverReorders:
    def test_ranked_order_matches_deterministic_ranking_regardless_of_model_response(self) -> None:
        candidates = (
            _candidate("p1", rating=3.0, distance_km=5.0),
            _candidate("p2", rating=5.0, distance_km=0.5),
        )
        # Adversarial: the model's narrative text even *claims* a different
        # winner — this must have zero effect on `ranked`'s real order,
        # because the code never reads an order/rank field from parsed JSON.
        response = json.dumps({"narrative": "Clinic p1 is clearly the best choice here.", "confidence": 0.9})
        agent = _agent(texts=[response])

        result = agent.rank(
            candidates=candidates, context=_context(), service_category="dental", person_id=NodeId("person-1")
        )

        top_reason = result.narrative
        assert result.ranked[0].provider_id == NodeId("p2")  # the real, deterministic #1
        assert top_reason == "Clinic p1 is clearly the best choice here."  # gloss text, not authoritative

    def test_narrative_and_confidence_are_carried_through(self) -> None:
        candidates = (_candidate("p1", rating=4.0, distance_km=1.0),)
        response = json.dumps({"narrative": "p1 is the only real option here.", "confidence": 0.77})
        agent = _agent(texts=[response])

        result = agent.rank(
            candidates=candidates, context=_context(), service_category="dental", person_id=NodeId("person-1")
        )

        assert result.narrative == "p1 is the only real option here."
        assert result.confidence == 0.77
        assert result.model_tier == "pro"


class TestEmptyCandidates:
    def test_no_candidates_short_circuits_without_a_model_call(self) -> None:
        fake_models = FakeModels(texts=["should never be called"])
        agent = ProviderRankingAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))

        result = agent.rank(
            candidates=(), context=_context(), service_category="dental", person_id=NodeId("person-1")
        )

        assert result.ranked == ()
        assert result.model_tier == "deterministic"
        assert fake_models.calls == []  # no Gemini call was made — real cost discipline


def test_agent_id_is_a52() -> None:
    assert str(AGENT_ID) == "A52"
