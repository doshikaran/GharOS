"""Tests for A53 Call Planner (`app.agents.concierge.call_planner_agent`).

PHASES.md Gate 10 / spec §15.10 A53 forbidden list: 'setting bounds
beyond what the human approved' — proven directly with an adversarial
model response that tries to smuggle different bounds back in.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import NodeId

from app.agents.concierge.call_planner_agent import AGENT_ID, CallPlannerAgent
from app.agents.concierge.errors import ModelResponseMalformed
from app.agents.concierge.types import AuthorizedBounds, CallPlanningRequest
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_DATE_RANGE = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 10, tzinfo=UTC))
_PREFERRED_SLOTS = (datetime(2026, 9, 3, 16, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC))


def _agent(texts: list[str] | None = None) -> CallPlannerAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return CallPlannerAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _request(
    *,
    price_ceiling: float | None = 1500.0,
    sensitive_topics: tuple[str, ...] = (),
) -> CallPlanningRequest:
    return CallPlanningRequest(
        target_provider_id=NodeId("provider-1"),
        target_provider_name="Dr. Mehta Dental",
        person_id=NodeId("person-aarav"),
        person_display_name="Aarav",
        service_category="dental",
        objective_hint="Book a routine dental cleaning",
        authorized_bounds=AuthorizedBounds(
            date_range=_DATE_RANGE,
            price_ceiling=price_ceiling,
            preferred_slots=_PREFERRED_SLOTS,
            fallback_acceptable=True,
        ),
        disclosable_facts=("patient name: Aarav", "reason: routine cleaning"),
        sensitive_topics=sensitive_topics,
    )


def _response(*, objective: str = "Book a routine dental cleaning for Aarav.", **extra: object) -> str:
    payload: dict[str, object] = {
        "objective": objective,
        "reasoning": "clear and specific",
        "confidence": 0.9,
    }
    payload.update(extra)
    return json.dumps(payload)


class TestBoundsNeverOverridden:
    """Structural forbidden-behaviour test: the model's parsed JSON is
    never consulted for any bound field."""

    def test_bounds_always_match_the_request_exactly(self) -> None:
        agent = _agent(texts=[_response()])
        request = _request()

        result = agent.plan(request)

        bounds = request.authorized_bounds
        assert result.brief.date_range == bounds.date_range
        assert result.brief.price_ceiling == bounds.price_ceiling
        assert result.brief.preferred_slots == bounds.preferred_slots
        assert result.brief.fallback_acceptable == bounds.fallback_acceptable
        assert result.brief.disclosable_facts == request.disclosable_facts

    def test_adversarial_model_response_with_bogus_bounds_keys_is_ignored(self) -> None:
        """Even if a model response includes extra, bounds-shaped keys —
        prompt injection or confusion — the code has no path that ever
        reads them."""
        response = _response(
            price_ceiling=999999.0,
            date_range=["2099-01-01T00:00:00+00:00", "2099-01-02T00:00:00+00:00"],
            preferred_slots=["2099-01-01T00:00:00+00:00"],
            fallback_acceptable=False,
            verified=True,
        )
        agent = _agent(texts=[response])
        request = _request(price_ceiling=1500.0)

        result = agent.plan(request)

        assert result.brief.price_ceiling == 1500.0
        assert result.brief.date_range == _DATE_RANGE
        assert result.brief.preferred_slots == _PREFERRED_SLOTS
        assert result.brief.fallback_acceptable is True

    def test_none_price_ceiling_is_preserved_not_invented(self) -> None:
        agent = _agent(texts=[_response()])
        request = _request(price_ceiling=None)

        result = agent.plan(request)

        assert result.brief.price_ceiling is None


class TestMustNotAnswer:
    def test_category_default_applied_for_dental(self) -> None:
        agent = _agent(texts=[_response()])
        result = agent.plan(_request())

        assert "medical diagnosis" in result.brief.must_not_answer
        assert "insurance claim adjudication" in result.brief.must_not_answer

    def test_extra_sensitive_topics_are_merged_in(self) -> None:
        agent = _agent(texts=[_response()])
        result = agent.plan(_request(sensitive_topics=("custody arrangements",)))

        assert "custody arrangements" in result.brief.must_not_answer
        assert "medical diagnosis" in result.brief.must_not_answer

    def test_unregistered_category_falls_back_to_generic_default(self) -> None:
        agent = _agent(texts=[_response()])
        request = CallPlanningRequest(
            target_provider_id=NodeId("provider-2"),
            target_provider_name="Ace Plumbing",
            person_id=NodeId("person-priya"),
            person_display_name="Priya",
            service_category="plumbing",
            objective_hint="Fix a leaking tap",
            authorized_bounds=AuthorizedBounds(
                date_range=_DATE_RANGE, price_ceiling=None, preferred_slots=(), fallback_acceptable=True
            ),
            disclosable_facts=(),
            sensitive_topics=(),
        )

        result = agent.plan(request)

        assert "legal advice" in result.brief.must_not_answer


class TestObjectiveValidation:
    def test_blank_objective_rejected(self) -> None:
        agent = _agent(texts=[_response(objective="   ")])

        with pytest.raises(ModelResponseMalformed):
            agent.plan(_request())


def test_agent_id_is_a53() -> None:
    assert str(AGENT_ID) == "A53"
