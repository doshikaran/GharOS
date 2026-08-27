"""Tests for A25 Window Scheduling
(`app.agents.intention_action.window_scheduling_agent`).

PHASES.md Phase 9's own acceptance list, this module's share of it:
- Finds a window where person AND counterparty are available AND history
  suggests completion.
- Person availability and historical likelihood are deterministic (no
  model call); counterparty free text is Flash with a real Pro-tier
  fallback on ambiguity/low confidence.
- Never guesses a window when everything is excluded.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId

from app.agents.intention_action.errors import ModelResponseMalformed
from app.agents.intention_action.types import WindowFindingRequest
from app.agents.intention_action.window_scheduling_agent import AGENT_ID, WindowSchedulingAgent
from app.reasoning.gemini_client import GeminiClient
from tests.conftest import make_provenance

from ._gemini_fakes import FakeModels, fake_router

_SATURDAY_9AM = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
_SATURDAY_3PM = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)
_SATURDAY_330PM = datetime(2026, 8, 22, 15, 30, tzinfo=UTC)
_SATURDAY_10AM = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)


def _agent(texts: list[str] | None = None) -> WindowSchedulingAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return WindowSchedulingAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _nap_constraint(*, severity: ConstraintSeverity = ConstraintSeverity.SOFT) -> Constraint:
    return Constraint(
        id=NodeId("constraint-dadi-nap"),
        provenance=make_provenance(),
        kind=ConstraintKind.SCHEDULE,
        severity=severity,
        validity_start=None,
        validity_end=None,
        structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"},
        original_text="naps most afternoons between 2 and 4",
    )


def _request(
    *,
    candidate_windows: tuple[tuple[datetime, datetime], ...],
    person_schedule_constraints: tuple[Constraint, ...] = (),
    provider_id: NodeId | None = None,
    provider_availability_notes: str | None = None,
    window_blocker_pattern_support: int = 0,
    outcome_count: int = 0,
) -> WindowFindingRequest:
    return WindowFindingRequest(
        obligation_id=NodeId("obligation-pharmacy"),
        person_id=NodeId("person-priya"),
        obligation_kind_description="pharmacy errand",
        candidate_windows=candidate_windows,
        person_schedule_constraints=person_schedule_constraints,
        provider_id=provider_id,
        provider_availability_notes=provider_availability_notes,
        window_blocker_pattern_support=window_blocker_pattern_support,
        outcome_count=outcome_count,
    )


class TestPurelyDeterministicNoProvider:
    def test_picks_the_available_window_over_the_soft_avoid_window(self) -> None:
        agent = _agent()
        request = _request(
            candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM), (_SATURDAY_3PM, _SATURDAY_330PM)),
            person_schedule_constraints=(_nap_constraint(),),
        )

        result = agent.find_window(request)

        assert result.best_window == (_SATURDAY_9AM, _SATURDAY_10AM)
        assert result.model_tier == "deterministic"

    def test_hard_blocked_window_is_never_chosen(self) -> None:
        agent = _agent()
        request = _request(
            candidate_windows=((_SATURDAY_3PM, _SATURDAY_330PM),),
            person_schedule_constraints=(_nap_constraint(severity=ConstraintSeverity.HARD),),
        )

        result = agent.find_window(request)

        assert result.best_window is None
        assert result.evaluations[0].overall_recommended is False

    def test_all_windows_excluded_returns_none_never_a_guess(self) -> None:
        agent = _agent()
        request = _request(
            candidate_windows=((_SATURDAY_3PM, _SATURDAY_330PM),),
            person_schedule_constraints=(_nap_constraint(severity=ConstraintSeverity.HARD),),
        )

        result = agent.find_window(request)

        assert result.best_window is None


class TestHistoricalLikelihood:
    def test_repeated_window_blocker_pattern_marks_unlikely(self) -> None:
        agent = _agent()
        request = _request(
            candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),),
            window_blocker_pattern_support=3,
        )

        result = agent.find_window(request)

        assert result.evaluations[0].historical_likelihood == "unlikely"

    def test_no_evidence_at_all_is_insufficient_data(self) -> None:
        agent = _agent()
        request = _request(candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),))

        result = agent.find_window(request)

        assert result.evaluations[0].historical_likelihood == "insufficient_data"

    def test_real_completion_outcomes_and_no_pattern_is_likely(self) -> None:
        agent = _agent()
        request = _request(candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),), outcome_count=2)

        result = agent.find_window(request)

        assert result.evaluations[0].historical_likelihood == "likely"


class TestCounterpartyAvailability:
    def test_clean_flash_verdict_used_without_escalation(self) -> None:
        response = json.dumps(
            {
                "per_window": [{"index": 0, "verdict": "available", "reasoning": "within stated hours"}],
                "confidence": 0.95,
            }
        )
        agent = _agent(texts=[response])
        request = _request(
            candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),),
            provider_id=NodeId("provider-pharmacy"),
            provider_availability_notes="Open Mon-Sat 8am-8pm",
        )

        result = agent.find_window(request)

        assert result.best_window == (_SATURDAY_9AM, _SATURDAY_10AM)
        assert result.model_tier == "flash"
        assert result.evaluations[0].counterparty_availability == "available"

    def test_low_confidence_escalates_to_pro(self) -> None:
        flash_response = json.dumps(
            {
                "per_window": [{"index": 0, "verdict": "cannot_determine", "reasoning": "notes are unclear"}],
                "confidence": 0.4,
            }
        )
        pro_verdict = {"index": 0, "verdict": "available", "reasoning": "by appointment, this slot works"}
        pro_response = json.dumps({"per_window": [pro_verdict], "confidence": 0.85})
        agent = _agent(texts=[flash_response, pro_response])
        request = _request(
            candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),),
            provider_id=NodeId("provider-pharmacy"),
            provider_availability_notes="by appointment only, call ahead",
        )

        result = agent.find_window(request)

        assert result.model_tier == "pro"
        assert result.evaluations[0].counterparty_availability == "available"

    def test_unavailable_counterparty_excludes_the_window(self) -> None:
        response = json.dumps(
            {
                "per_window": [{"index": 0, "verdict": "unavailable", "reasoning": "closed Saturdays"}],
                "confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        request = _request(
            candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),),
            provider_id=NodeId("provider-pharmacy"),
            provider_availability_notes="Closed Saturdays",
        )

        result = agent.find_window(request)

        assert result.best_window is None

    def test_malformed_response_raises(self) -> None:
        agent = _agent(texts=["not json at all"])
        request = _request(
            candidate_windows=((_SATURDAY_9AM, _SATURDAY_10AM),),
            provider_id=NodeId("provider-pharmacy"),
            provider_availability_notes="Mon-Fri 9-5",
        )

        with pytest.raises(ModelResponseMalformed):
            agent.find_window(request)


def test_agent_id_is_a25() -> None:
    assert str(AGENT_ID) == "A25"
