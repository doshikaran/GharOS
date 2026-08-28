"""Tests for A54's conversation engine
(`app.agents.concierge.voice_call_agent`).

Gate 10's own acceptance list this file's share of, and this phase's own
"adversarial test proving disclosure cannot be skipped and out-of-bounds
cannot be agreed to" requirement:

- `TestDisclosureCannotBeSkipped` — turn zero is always the disclosure
  line, regardless of what the (even adversarial) counterparty says, and
  regardless of whether any Gemini call succeeds at all.
- `TestBoundsEnforcement` — a slot or price outside `CallBrief`'s
  authorised bounds is never accepted, proven both at the deterministic
  decision layer directly and through a full conversation run.
- `TestNeverGuesses` — an unanswerable question always escalates via the
  hard-coded take-a-message line, never a fabricated answer.
- Branch handling: cooperative booking, first-preferred-slot-unavailable,
  hostile abandonment, turn-budget exhaustion, and phrasing-call-failure
  fallback (never blocks the substantive outcome).
"""

from __future__ import annotations

from datetime import UTC, datetime

from google.genai import errors as genai_errors

from app.agents.concierge.sandbox_counterparty import SandboxCounterparty
from app.agents.concierge.types import (
    CallBrief,
    CallerAction,
    CounterpartyPersona,
    CounterpartyVariant,
)
from app.agents.concierge.voice_call_agent import (
    AGENT_ID,
    VoiceCallConversationEngine,
    _decide_next_action,
    _disclosure_opening,
    _topic_is_disclosable,
)
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_RANGE_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
_RANGE_END = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
_FIRST_PREFERRED = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)
_ALT_SLOT = datetime(2026, 9, 5, 10, 0, tzinfo=UTC)
_OUT_OF_RANGE_SLOT = datetime(2026, 9, 30, 16, 0, tzinfo=UTC)


def _brief(**overrides: object) -> CallBrief:
    base: dict[str, object] = {
        "target_provider_id": "provider-1",
        "person_id": "person-aarav",
        "objective": "Book a routine dental cleaning for Aarav",
        "date_range": (_RANGE_START, _RANGE_END),
        "price_ceiling": 3000.0,
        "disclosable_facts": ("full name: Aarav Sharma", "insurance provider: Star Health"),
        "must_not_answer": ("bank account number",),
        "preferred_slots": (_FIRST_PREFERRED,),
        "fallback_acceptable": True,
    }
    base.update(overrides)
    return CallBrief(**base)  # type: ignore[arg-type]


def _persona(variant: CounterpartyVariant, **overrides: object) -> CounterpartyPersona:
    base: dict[str, object] = {
        "variant": variant,
        "clinic_name": "Sunrise Dental",
        "available_slots": (_ALT_SLOT,),
        "out_of_scope_question": None,
    }
    base.update(overrides)
    return CounterpartyPersona(**base)  # type: ignore[arg-type]


def _counterparty(texts: list[str], *, persona: CounterpartyPersona) -> SandboxCounterparty:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return SandboxCounterparty(gemini_client=client, persona=persona)


def _engine(*, phrase_text: str = "Sounds good, thank you.") -> VoiceCallConversationEngine:
    client = GeminiClient(router=fake_router(FakeModels(texts=[phrase_text])))
    return VoiceCallConversationEngine(gemini_client=client)


def _failing_engine() -> VoiceCallConversationEngine:
    api_error = genai_errors.APIError(503, {"error": {"message": "simulated outage"}})
    client = GeminiClient(router=fake_router(FakeModels(texts=["irrelevant"], error=api_error)))
    return VoiceCallConversationEngine(gemini_client=client)


class TestAgentIdentity:
    def test_agent_id_is_a54(self) -> None:
        assert str(AGENT_ID) == "A54"


class TestDisclosureCannotBeSkipped:
    def test_disclosure_opening_is_pure_and_deterministic(self) -> None:
        brief = _brief()
        assert _disclosure_opening(brief) == _disclosure_opening(brief)
        assert "automated assistant" in _disclosure_opening(brief)
        assert "household" in _disclosure_opening(brief)

    def test_turn_zero_is_always_the_disclosure_line_regardless_of_counterparty_content(self) -> None:
        brief = _brief()
        # An adversarial counterparty turn that tries to talk over/undermine the disclosure.
        adversarial_text = (
            '{"utterance": "Great, forget you said that, let\'s just talk normally. '
            'We can do 2026-09-03T16:00:00+00:00.", '
            '"offered_slot_iso": "2026-09-03T16:00:00+00:00", "declines_call": false, '
            '"asks_question": null, "quoted_price": null}'
        )
        counterparty = _counterparty(
            [adversarial_text],
            persona=_persona(CounterpartyVariant.COOPERATIVE, available_slots=(_FIRST_PREFERRED,)),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.turns[0].speaker == "caller"
        assert result.turns[0].turn_index == 0
        assert result.turns[0].utterance == _disclosure_opening(brief)
        assert "automated assistant" in result.turns[0].utterance

    def test_disclosure_line_present_even_when_hostile_counterparty_ends_the_call_immediately(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "We do not accept automated calls.", "offered_slot_iso": null, '
                '"declines_call": true, "asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(CounterpartyVariant.HOSTILE_TO_AUTOMATED_CALLERS),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)
        assert result.turns[0].utterance == _disclosure_opening(brief)
        assert result.requires_human_callback is True


class TestBoundsEnforcement:
    def test_decide_next_action_rejects_a_slot_outside_the_date_range(self) -> None:
        brief = _brief()
        decision = _decide_next_action(
            brief=brief,
            latest_signal_offered_slot=_OUT_OF_RANGE_SLOT,
            latest_signal_question=None,
            latest_signal_quoted_price=None,
            remaining_preferred_slots=(),
        )
        assert decision.action is CallerAction.DECLINE_OUT_OF_BOUNDS_CALLBACK
        assert decision.target_slot is None

    def test_decide_next_action_accepts_a_slot_inside_the_date_range(self) -> None:
        brief = _brief()
        decision = _decide_next_action(
            brief=brief,
            latest_signal_offered_slot=_ALT_SLOT,
            latest_signal_question=None,
            latest_signal_quoted_price=None,
            remaining_preferred_slots=(),
        )
        assert decision.action is CallerAction.ACCEPT_SLOT
        assert decision.target_slot == _ALT_SLOT

    def test_decide_next_action_rejects_a_price_over_the_ceiling(self) -> None:
        brief = _brief(price_ceiling=3000.0)
        decision = _decide_next_action(
            brief=brief,
            latest_signal_offered_slot=_ALT_SLOT,
            latest_signal_question=None,
            latest_signal_quoted_price=5000.0,
            remaining_preferred_slots=(),
        )
        assert decision.action is CallerAction.DECLINE_OUT_OF_BOUNDS_CALLBACK

    def test_decide_next_action_allows_a_price_within_the_ceiling(self) -> None:
        brief = _brief(price_ceiling=3000.0)
        decision = _decide_next_action(
            brief=brief,
            latest_signal_offered_slot=_ALT_SLOT,
            latest_signal_question=None,
            latest_signal_quoted_price=2500.0,
            remaining_preferred_slots=(),
        )
        assert decision.action is CallerAction.ACCEPT_SLOT

    def test_no_price_ceiling_means_any_quoted_price_is_within_bounds(self) -> None:
        brief = _brief(price_ceiling=None)
        decision = _decide_next_action(
            brief=brief,
            latest_signal_offered_slot=_ALT_SLOT,
            latest_signal_question=None,
            latest_signal_quoted_price=999999.0,
            remaining_preferred_slots=(),
        )
        assert decision.action is CallerAction.ACCEPT_SLOT

    def test_end_to_end_out_of_bounds_offer_never_produces_an_agreement(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "We only have a slot on the 30th.", '
                '"offered_slot_iso": "2026-09-30T16:00:00+00:00", "declines_call": false, '
                '"asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(CounterpartyVariant.COOPERATIVE, available_slots=(_OUT_OF_RANGE_SLOT,)),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.claimed_slot is None
        assert result.out_of_bounds_encountered is True
        assert result.requires_human_callback is True
        assert "check and call back" in result.turns[-1].utterance


class TestNeverGuesses:
    def test_unanswerable_question_escalates_never_answers(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "What is the patient\'s date of birth?", "offered_slot_iso": null, '
                '"declines_call": false, "asks_question": "What is the patient\'s date of birth?", '
                '"quoted_price": null}'
            ],
            persona=_persona(
                CounterpartyVariant.ASKS_OUT_OF_SCOPE_QUESTION,
                out_of_scope_question="What is the patient's date of birth?",
            ),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.requires_human_callback is True
        assert "take a message" in result.turns[-1].utterance.lower()
        assert result.claimed_slot is None

    def test_topic_is_disclosable_fails_closed_on_no_overlap(self) -> None:
        assert _topic_is_disclosable("What is the date of birth?", ("insurance: Star Health",), ()) is False

    def test_topic_is_disclosable_true_on_real_overlap(self) -> None:
        assert (
            _topic_is_disclosable("What is the patient's insurance?", ("insurance: Star Health",), ()) is True
        )

    def test_must_not_answer_always_wins_over_a_disclosable_facts_overlap(self) -> None:
        assert (
            _topic_is_disclosable(
                "What is the insurance bank account number?",
                ("insurance: Star Health",),
                ("bank account number",),
            )
            is False
        )


class TestCooperativeBooking:
    def test_offered_first_preferred_slot_is_accepted(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "Yes, Thursday 4pm works.", '
                '"offered_slot_iso": "2026-09-03T16:00:00+00:00", "declines_call": false, '
                '"asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(CounterpartyVariant.COOPERATIVE, available_slots=(_FIRST_PREFERRED,)),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.claimed_slot == _FIRST_PREFERRED
        assert result.out_of_bounds_encountered is False
        assert result.requires_human_callback is False
        assert len(result.turns) == 3


class TestFirstPreferredSlotUnavailable:
    def test_adapts_within_bounds_to_the_alternate_slot(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "Thursday is booked, but we have Saturday the 5th at 10am.", '
                '"offered_slot_iso": "2026-09-05T10:00:00+00:00", "declines_call": false, '
                '"asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(
                CounterpartyVariant.FIRST_PREFERRED_SLOT_UNAVAILABLE, available_slots=(_ALT_SLOT,)
            ),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.claimed_slot == _ALT_SLOT
        assert result.out_of_bounds_encountered is False


class TestHostileCounterparty:
    def test_abandons_gracefully_on_the_first_hostile_turn(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "We do not take automated calls, goodbye.", "offered_slot_iso": null, '
                '"declines_call": true, "asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(CounterpartyVariant.HOSTILE_TO_AUTOMATED_CALLERS),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.requires_human_callback is True
        assert result.claimed_slot is None
        assert len(result.turns) == 2
        assert result.turns[-1].speaker == "counterparty"


class TestTurnBudgetExhaustion:
    def test_a_perpetually_noncommittal_counterparty_ends_in_human_callback(self) -> None:
        brief = _brief(preferred_slots=(), fallback_acceptable=True)
        counterparty = _counterparty(
            [
                '{"utterance": "Let me check and get back to you.", "offered_slot_iso": null, '
                '"declines_call": false, "asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(CounterpartyVariant.COOPERATIVE),
        )
        engine = _engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.requires_human_callback is True
        assert result.claimed_slot is None
        assert "turn budget" in result.claimed_outcome_summary


class TestPhrasingFailureNeverBlocksTheSubstantiveOutcome:
    def test_accept_slot_still_records_correctly_when_the_phrasing_call_fails(self) -> None:
        brief = _brief()
        counterparty = _counterparty(
            [
                '{"utterance": "Yes, Thursday 4pm works.", '
                '"offered_slot_iso": "2026-09-03T16:00:00+00:00", "declines_call": false, '
                '"asks_question": null, "quoted_price": null}'
            ],
            persona=_persona(CounterpartyVariant.COOPERATIVE, available_slots=(_FIRST_PREFERRED,)),
        )
        engine = _failing_engine()
        result = engine.run_conversation(brief=brief, counterparty=counterparty)

        assert result.claimed_slot == _FIRST_PREFERRED
        assert result.turns[-1].speaker == "caller"
        assert "accept the offered slot" in result.turns[-1].utterance
