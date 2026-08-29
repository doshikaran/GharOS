"""Tests for `app.agents.concierge.ranking` — A52's deterministic,
no-model-call scoring core.

PHASES.md Gate 10's own acceptance list, this module's share of it:
- "Ranking explainable — the user sees why #1 is #1" — every ranked
  entry carries real, specific `reasons` and a full `score_components`
  breakdown, never an opaque score.
- "a provider who no-showed before is demoted" — proven directly, no
  Gemini mocking needed (this module makes no model call at all).
- Pain/urgency reported -> the search prioritises earliest availability
  over rating (spec §13.2 Step 1).
"""

from __future__ import annotations

from contracts.graph_types import NodeId

from app.agents.concierge.ranking import rank_candidates, score_candidate
from app.agents.concierge.types import (
    ProviderCandidate,
    ProviderReliabilitySignal,
    RankingContext,
    UrgencyLevel,
)


def _candidate(
    provider_id: str,
    *,
    name: str = "Clinic",
    rating: float | None = 4.5,
    distance_km: float | None = 2.0,
    price_band: str | None = "$$",
    is_existing: bool = False,
) -> ProviderCandidate:
    return ProviderCandidate(
        provider_id=NodeId(provider_id),
        name=name,
        category="dental",
        rating=rating,
        distance_km=distance_km,
        availability_notes=None,
        price_band=price_band,
        specialisations=(),
        is_existing_household_provider=is_existing,
    )


def _context(
    *,
    urgency: UrgencyLevel = UrgencyLevel.ROUTINE,
    offsets: dict[NodeId, float] | None = None,
    reliability: dict[NodeId, ProviderReliabilitySignal] | None = None,
) -> RankingContext:
    return RankingContext(
        urgency=urgency,
        provider_earliest_offset_days=offsets or {},
        reliability_by_provider=reliability or {},
    )


class TestExplainability:
    def test_every_ranked_entry_has_real_specific_reasons(self) -> None:
        candidates = (
            _candidate("p1", rating=4.8, distance_km=1.2),
            _candidate("p2", rating=4.2, distance_km=3.0),
        )
        ranked = rank_candidates(candidates, _context())
        expected_components = {"rating", "distance", "availability", "price", "reliability"}

        for entry in ranked:
            assert entry.reasons
            for reason in entry.reasons:
                assert reason.strip()
            # No opaque ranking: the full breakdown is always published.
            assert set(entry.score_components) == expected_components

    def test_top_ranked_reasons_reference_its_own_real_numbers(self) -> None:
        candidates = (
            _candidate("p1", rating=4.9, distance_km=0.5),
            _candidate("p2", rating=3.0, distance_km=10.0),
        )
        ranked = rank_candidates(candidates, _context())

        assert ranked[0].provider_id == NodeId("p1")
        assert any("4.9" in reason for reason in ranked[0].reasons)
        assert any("0.5" in reason for reason in ranked[0].reasons)

    def test_rank_order_is_deterministic_by_score_descending(self) -> None:
        candidates = (
            _candidate("low", rating=2.0, distance_km=20.0),
            _candidate("high", rating=5.0, distance_km=0.1),
            _candidate("mid", rating=3.5, distance_km=5.0),
        )
        ranked = rank_candidates(candidates, _context())

        assert [entry.provider_id for entry in ranked] == [NodeId("high"), NodeId("mid"), NodeId("low")]
        assert [entry.rank for entry in ranked] == [1, 2, 3]


class TestReliabilityDemotion:
    """Gate 10's own literal test case: 'a provider who no-showed before
    is demoted.'"""

    def test_no_show_history_demotes_an_otherwise_top_candidate(self) -> None:
        no_show_signal = ProviderReliabilitySignal(
            provider_id=NodeId("no-show-provider"),
            no_show_count=1,
            on_time_count=0,
            rescheduled_count=0,
            unresponsive_count=0,
            total_outcomes_considered=1,
        )
        candidates = (
            # Glowing, closest — would win on every other factor alone.
            _candidate(
                "no-show-provider", name="Glowing Clinic", rating=5.0, distance_km=0.1, is_existing=True
            ),
            _candidate("clean-record", name="Ordinary Clinic", rating=4.0, distance_km=2.0, is_existing=True),
        )
        context = _context(reliability={NodeId("no-show-provider"): no_show_signal})

        ranked = rank_candidates(candidates, context)

        top = ranked[0]
        assert top.provider_id == NodeId("clean-record")
        no_show_entry = next(e for e in ranked if e.provider_id == NodeId("no-show-provider"))
        assert no_show_entry.demoted_for_reliability is True
        assert any("no-show" in reason for reason in no_show_entry.reasons)
        assert no_show_entry.rank > top.rank

    def test_new_provider_with_no_history_is_not_penalised(self) -> None:
        candidates = (_candidate("brand-new", is_existing=False),)
        ranked = rank_candidates(candidates, _context())

        assert ranked[0].demoted_for_reliability is False

    def test_existing_provider_with_on_time_history_is_not_demoted(self) -> None:
        on_time_signal = ProviderReliabilitySignal(
            provider_id=NodeId("reliable"),
            no_show_count=0,
            on_time_count=3,
            rescheduled_count=0,
            unresponsive_count=0,
            total_outcomes_considered=3,
        )
        candidates = (_candidate("reliable", is_existing=True),)
        context = _context(reliability={NodeId("reliable"): on_time_signal})

        ranked = rank_candidates(candidates, context)

        assert ranked[0].demoted_for_reliability is False
        assert any("on-time" in reason for reason in ranked[0].reasons)


class TestUrgencyReweighting:
    """spec §13.2 Step 1: pain reported -> urgency escalates -> earliest
    availability is prioritised over rating."""

    def test_elevated_urgency_prefers_earliest_availability_over_rating(self) -> None:
        candidates = (
            _candidate("high-rated-slow", rating=5.0, distance_km=1.0),
            _candidate("lower-rated-fast", rating=3.5, distance_km=1.0),
        )
        offsets = {NodeId("high-rated-slow"): 14.0, NodeId("lower-rated-fast"): 1.0}

        routine_context = _context(urgency=UrgencyLevel.ROUTINE, offsets=offsets)
        elevated_context = _context(urgency=UrgencyLevel.ELEVATED, offsets=offsets)
        routine_ranked = rank_candidates(candidates, routine_context)
        elevated_ranked = rank_candidates(candidates, elevated_context)

        assert routine_ranked[0].provider_id == NodeId("high-rated-slow")
        assert elevated_ranked[0].provider_id == NodeId("lower-rated-fast")


class TestScoreCandidate:
    def test_missing_optional_fields_score_neutrally_never_penalised(self) -> None:
        candidate = _candidate("unknown-fields", rating=None, distance_km=None, price_band=None)
        total, components, demoted, reasons = score_candidate(candidate, _context())

        assert components["rating"] == 0.5
        assert components["distance"] == 0.5
        assert components["price"] == 0.5
        assert demoted is False
        assert reasons  # still has at least the fallback reason
