"""Tests for A50 Requirement Clarifier
(`app.agents.concierge.requirement_clarifier_agent`).

PHASES.md Gate 10's own acceptance list, this module's share of it:
- "'Book a dentist' asks <=2 questions" — a real, code-enforced ceiling,
  tested directly against a scenario with more than two genuinely-unknown
  facts.
- Forbidden: asking what the graph already knows — a question targeting
  anything outside `candidate_unknowns` is rejected, not silently
  accepted.
- Pain/urgency reported -> urgency escalates, even overriding a model
  that misclassified the request as routine.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import json

import pytest
from contracts.graph_types import NodeId

from app.agents.concierge.errors import ModelResponseMalformed
from app.agents.concierge.requirement_clarifier_agent import (
    AGENT_ID,
    MAX_CLARIFYING_QUESTIONS,
    RequirementClarifierAgent,
)
from app.agents.concierge.types import ClarificationRequest, GraphKnownFact, UrgencyLevel
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(texts: list[str] | None = None) -> RequirementClarifierAgent:
    fake_models = FakeModels(texts=texts or ["should never be read"])
    return RequirementClarifierAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _request(
    *,
    household_request_text: str = "Book a dentist appointment for Aarav",
    candidate_unknowns: tuple[str, ...],
) -> ClarificationRequest:
    return ClarificationRequest(
        household_request_text=household_request_text,
        person_id=NodeId("person-aarav"),
        service_category="dental",
        known_facts=(
            GraphKnownFact(
                field="person_availability",
                value="free after 3pm on weekdays",
                source="neighbours(person_id, CONSTRAINS)",
            ),
        ),
        candidate_unknowns=candidate_unknowns,
    )


def _response(
    *,
    questions: list[dict[str, str]],
    assumptions: list[str] | None = None,
    urgency: str = "routine",
    urgency_reasoning: str = "no pain or urgency language in the request",
    confidence: float = 0.85,
) -> str:
    return json.dumps(
        {
            "questions": questions,
            "assumptions": assumptions or [],
            "urgency": urgency,
            "urgency_reasoning": urgency_reasoning,
            "confidence": confidence,
        }
    )


class TestQuestionCeiling:
    """Gate 10's literal checklist item: "'Book a dentist' asks <=2
    questions" — proven against a scenario with more than two genuinely
    unknown facts."""

    def test_more_than_two_unknowns_still_asks_at_most_two(self) -> None:
        candidate_unknowns = (
            "insurance_provider",
            "situation_urgency",
            "date_constraints",
            "provider_preference",
        )
        response = _response(
            questions=[
                {
                    "text": "Is this routine or is something hurting?",
                    "targets_unknown": "situation_urgency",
                    "decision_relevance": "determines urgency and ranking priority",
                },
                {
                    "text": "Any date constraints we should know about?",
                    "targets_unknown": "date_constraints",
                    "decision_relevance": "narrows the acceptable booking window",
                },
                {
                    "text": "Do you want to see the same dentist as before?",
                    "targets_unknown": "provider_preference",
                    "decision_relevance": "affects which provider gets called first",
                },
                {
                    "text": "What insurance provider should we mention?",
                    "targets_unknown": "insurance_provider",
                    "decision_relevance": "affects which providers are in-network",
                },
            ]
        )
        agent = _agent(texts=[response])

        result = agent.clarify(_request(candidate_unknowns=candidate_unknowns))

        assert len(result.questions) == MAX_CLARIFYING_QUESTIONS
        assert MAX_CLARIFYING_QUESTIONS == 2
        # The model's own top-2 ranking is honoured in order.
        assert result.questions[0].targets_unknown == "situation_urgency"
        assert result.questions[1].targets_unknown == "date_constraints"

    def test_skipped_candidates_become_assumptions_never_silently_dropped(self) -> None:
        candidate_unknowns = (
            "insurance_provider",
            "situation_urgency",
            "date_constraints",
            "provider_preference",
        )
        response = _response(
            questions=[
                {
                    "text": "Is this routine or is something hurting?",
                    "targets_unknown": "situation_urgency",
                    "decision_relevance": "urgency",
                },
                {
                    "text": "Any date constraints?",
                    "targets_unknown": "date_constraints",
                    "decision_relevance": "window",
                },
            ],
            assumptions=["Assuming the household is fine with a new provider if needed."],
        )
        agent = _agent(texts=[response])

        result = agent.clarify(_request(candidate_unknowns=candidate_unknowns))

        asked = {q.targets_unknown for q in result.questions}
        assert asked == {"situation_urgency", "date_constraints"}
        # Every unasked candidate is accounted for somewhere in assumptions.
        for unknown in ("insurance_provider", "provider_preference"):
            assert any(unknown in assumption for assumption in result.assumptions)

    def test_zero_unknowns_asks_zero_questions(self) -> None:
        response = _response(questions=[])
        agent = _agent(texts=[response])

        result = agent.clarify(_request(candidate_unknowns=()))

        assert result.questions == ()
        assert result.resolved_from_graph[0].field == "person_availability"


class TestForbiddenAskingWhatGraphKnows:
    """spec §15.10 A50 forbidden list: 'asking what the graph already
    knows' — structurally enforced by rejecting any question targeting
    something outside `candidate_unknowns`."""

    def test_question_targeting_unlisted_fact_is_rejected(self) -> None:
        response = _response(
            questions=[
                {
                    "text": "What's the person's availability?",
                    "targets_unknown": "person_availability",  # already known, not a real candidate
                    "decision_relevance": "n/a",
                }
            ]
        )
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.clarify(_request(candidate_unknowns=("situation_urgency",)))

    def test_question_targeting_invented_key_is_rejected(self) -> None:
        response = _response(
            questions=[
                {
                    "text": "What's your favourite colour?",
                    "targets_unknown": "favourite_colour",
                    "decision_relevance": "n/a",
                }
            ]
        )
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.clarify(_request(candidate_unknowns=("situation_urgency",)))

    def test_blank_question_text_is_rejected(self) -> None:
        response = _response(
            questions=[{"text": "   ", "targets_unknown": "situation_urgency", "decision_relevance": "n/a"}]
        )
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.clarify(_request(candidate_unknowns=("situation_urgency",)))


class TestUrgencyDetection:
    def test_model_reported_elevated_urgency_is_honoured(self) -> None:
        response = _response(questions=[], urgency="elevated", urgency_reasoning="patient reports tooth pain")
        agent = _agent(texts=[response])

        result = agent.clarify(
            _request(
                household_request_text="Aarav's tooth really hurts, can we get him seen soon",
                candidate_unknowns=(),
            )
        )

        assert result.urgency is UrgencyLevel.ELEVATED

    def test_keyword_backstop_overrides_model_missing_urgency(self) -> None:
        """A real urgency signal in the household's own words is never
        silently missed, even if the model itself misclassifies it."""
        response = _response(questions=[], urgency="routine", urgency_reasoning="nothing notable")
        agent = _agent(texts=[response])

        result = agent.clarify(
            _request(household_request_text="Aarav's tooth is hurting badly", candidate_unknowns=())
        )

        assert result.urgency is UrgencyLevel.ELEVATED
        assert "overriding" in result.urgency_reasoning

    def test_no_urgency_language_stays_routine(self) -> None:
        response = _response(questions=[], urgency="routine")
        agent = _agent(texts=[response])

        result = agent.clarify(
            _request(household_request_text="Book Aarav's routine dental cleaning", candidate_unknowns=())
        )

        assert result.urgency is UrgencyLevel.ROUTINE

    def test_unrecognised_urgency_value_rejected(self) -> None:
        response = _response(questions=[], urgency="somewhat-urgent")
        agent = _agent(texts=[response])

        with pytest.raises(ModelResponseMalformed):
            agent.clarify(_request(candidate_unknowns=()))


def test_agent_id_is_a50() -> None:
    assert str(AGENT_ID) == "A50"
