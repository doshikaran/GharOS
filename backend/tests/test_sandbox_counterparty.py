"""Tests for `app.agents.concierge.sandbox_counterparty.SandboxCounterparty`
— the real, second, independently-reasoning LLM agent ADR-016 requires
(PHASES.md Phase 10). A fake `GeminiClient` stands in for the live call
(matching every other LLM-backed agent test in this codebase,
`_gemini_fakes.py`'s established pattern) — production code always makes
a real Flash call; only tests inject a queued response.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from google.genai import errors as genai_errors

from app.agents.concierge.errors import ModelResponseMalformed
from app.agents.concierge.sandbox_counterparty import SandboxCounterparty
from app.agents.concierge.types import CounterpartyPersona, CounterpartyVariant
from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router

_SLOT = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


def _persona(
    variant: CounterpartyVariant = CounterpartyVariant.COOPERATIVE, **overrides: object
) -> CounterpartyPersona:
    base: dict[str, object] = {
        "variant": variant,
        "clinic_name": "Sunrise Dental",
        "available_slots": (_SLOT,),
        "out_of_scope_question": None,
    }
    base.update(overrides)
    return CounterpartyPersona(**base)  # type: ignore[arg-type]


def _counterparty(text: str, *, persona: CounterpartyPersona | None = None) -> SandboxCounterparty:
    fake_models = FakeModels(texts=[text])
    client = GeminiClient(router=fake_router(fake_models))
    return SandboxCounterparty(gemini_client=client, persona=persona or _persona())


class TestRespondParsing:
    def test_parses_a_well_formed_offer(self) -> None:
        counterparty = _counterparty(
            '{"utterance": "We can do Thursday at 4pm.", "offered_slot_iso": "2026-09-03T16:00:00+00:00", '
            '"declines_call": false, "asks_question": null}'
        )
        signal = counterparty.respond(
            conversation_so_far=(), latest_caller_utterance="Hello, calling about a checkup."
        )
        assert signal.utterance == "We can do Thursday at 4pm."
        assert signal.offered_slot == _SLOT
        assert signal.declines_call is False
        assert signal.asks_question is None

    def test_parses_a_declined_call(self) -> None:
        counterparty = _counterparty(
            '{"utterance": "We do not take automated calls.", "offered_slot_iso": null, '
            '"declines_call": true, "asks_question": null}',
            persona=_persona(CounterpartyVariant.HOSTILE_TO_AUTOMATED_CALLERS),
        )
        signal = counterparty.respond(
            conversation_so_far=(), latest_caller_utterance="Hello, this is an automated assistant."
        )
        assert signal.declines_call is True
        assert signal.offered_slot is None

    def test_parses_a_question(self) -> None:
        counterparty = _counterparty(
            '{"utterance": "First, what is the date of birth?", "offered_slot_iso": null, '
            '"declines_call": false, "asks_question": "What is the patient\'s date of birth?"}',
            persona=_persona(
                CounterpartyVariant.ASKS_OUT_OF_SCOPE_QUESTION,
                out_of_scope_question="What is the patient's date of birth?",
            ),
        )
        signal = counterparty.respond(
            conversation_so_far=(), latest_caller_utterance="Hi, calling about a checkup."
        )
        assert signal.asks_question == "What is the patient's date of birth?"

    def test_malformed_json_raises_model_response_malformed(self) -> None:
        counterparty = _counterparty("not json at all")
        with pytest.raises(ModelResponseMalformed):
            counterparty.respond(conversation_so_far=(), latest_caller_utterance="Hi")

    def test_missing_utterance_raises_model_response_malformed(self) -> None:
        counterparty = _counterparty(
            '{"offered_slot_iso": null, "declines_call": false, "asks_question": null}'
        )
        with pytest.raises(ModelResponseMalformed):
            counterparty.respond(conversation_so_far=(), latest_caller_utterance="Hi")

    def test_invalid_offered_slot_iso_raises_model_response_malformed(self) -> None:
        counterparty = _counterparty(
            '{"utterance": "Sure.", "offered_slot_iso": "not-a-date", '
            '"declines_call": false, "asks_question": null}'
        )
        with pytest.raises(ModelResponseMalformed):
            counterparty.respond(conversation_so_far=(), latest_caller_utterance="Hi")


class TestCallFailurePropagates:
    def test_gemini_call_failure_propagates_never_a_fabricated_turn(self) -> None:
        api_error = genai_errors.APIError(503, {"error": {"message": "simulated outage"}})
        fake_models = FakeModels(texts=["irrelevant"], error=api_error)
        client = GeminiClient(router=fake_router(fake_models))
        counterparty = SandboxCounterparty(gemini_client=client, persona=_persona())
        with pytest.raises(GeminiCallFailed):
            counterparty.respond(conversation_so_far=(), latest_caller_utterance="Hi")


class TestNeverAllowlisted:
    def test_sandbox_agent_id_is_not_on_the_pro_tier_allowlist(self) -> None:
        from app.agents.concierge.sandbox_counterparty import AGENT_ID
        from app.reasoning.model_router import PRO_TIER_ALLOWLIST

        assert AGENT_ID not in PRO_TIER_ALLOWLIST
