"""Tests for A64 Language & Script Identifier
(`app.agents.voice.language_script_identifier_agent`).

Covers: confident per-span tagging, the genuinely-ambiguous Hindi/Marathi
short-utterance fallback (spec §15.11 A64 failure mode), the no-speaker-
profile edge case, malformed-response rejection, and the Flash-only tier
discipline (never on the Pro-tier allowlist).
"""

from __future__ import annotations

import json

import pytest
from contracts.graph_types import LanguageProfile, LiteracyMode, NodeId

from app.agents.voice.errors import ModelResponseMalformed
from app.agents.voice.language_script_identifier_agent import (
    AGENT_ID,
    LanguageScriptIdentifierAgent,
)
from app.agents.voice.types import LanguageIdentificationRequest, SpeakerLanguageContext, TranscriptToken
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import PRO_TIER_ALLOWLIST

from ._gemini_fakes import FakeModels, fake_router


def _agent(*, texts: list[str]) -> LanguageScriptIdentifierAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return LanguageScriptIdentifierAgent(gemini_client=client)


def _speaker(*, primary_language: str | None) -> SpeakerLanguageContext:
    if primary_language is None:
        return SpeakerLanguageContext(person_id=None, language_profile=None)
    return SpeakerLanguageContext(
        person_id=NodeId("person-1"),
        language_profile=LanguageProfile(
            primary_language=primary_language,
            languages_understood=(primary_language, "en"),
            script_preference="devanagari",
            code_mixing_profile=f"{primary_language}-en",
            formality_preference="informal",
            literacy_mode=LiteracyMode.BOTH,
        ),
    )


def _request(*, raw_text: str, primary_language: str | None) -> LanguageIdentificationRequest:
    return LanguageIdentificationRequest(
        turn_id="turn-1",
        raw_text=raw_text,
        tokens=(TranscriptToken(text=raw_text, start_ms=0, end_ms=1000, asr_confidence=0.9),),
        speaker=_speaker(primary_language=primary_language),
    )


class TestConfidentTagging:
    def test_confident_code_mixed_turn_produces_per_span_tags(self) -> None:
        raw_text = "Aarav ko Friday ko field trip hai"
        response = json.dumps(
            {
                "spans": [
                    {
                        "text": "Aarav ko Friday ko",
                        "start_char": 0,
                        "end_char": 19,
                        "language": "hi",
                        "confidence": 0.9,
                        "ambiguous_between": [],
                    },
                    {
                        "text": "field trip",
                        "start_char": 20,
                        "end_char": 30,
                        "language": "en",
                        "confidence": 0.95,
                        "ambiguous_between": [],
                    },
                    {
                        "text": "hai",
                        "start_char": 31,
                        "end_char": 34,
                        "language": "hi",
                        "confidence": 0.92,
                        "ambiguous_between": [],
                    },
                ],
                "overall_confidence": 0.92,
            }
        )
        agent = _agent(texts=[response])

        result = agent.identify(_request(raw_text=raw_text, primary_language="hi"))

        assert [span.language for span in result.spans] == ["hi", "en", "hi"]
        assert all(not span.fallback_applied for span in result.spans)
        assert result.model_tier == "flash"
        assert result.turn_id == "turn-1"


class TestGenuineHindiMarathiAmbiguity:
    """ "Aaj nahi" ("not today") is genuinely ambiguous between Hindi and
    Marathi — identical vocabulary, no grammatical marker either language
    can be ruled out by. Spec §15.11 A64 failure mode: fall back to the
    speaker's primary_language, flag low confidence."""

    def _ambiguous_response(self) -> str:
        return json.dumps(
            {
                "spans": [
                    {
                        "text": "Aaj nahi",
                        "start_char": 0,
                        "end_char": 8,
                        "language": "hi",
                        "confidence": 0.4,
                        "ambiguous_between": ["hi", "mr"],
                    }
                ],
                "overall_confidence": 0.4,
            }
        )

    def test_falls_back_to_speaker_primary_language(self) -> None:
        agent = _agent(texts=[self._ambiguous_response()])

        result = agent.identify(_request(raw_text="Aaj nahi", primary_language="mr"))

        span = result.spans[0]
        assert span.language == "mr"
        assert span.fallback_applied is True
        assert span.confidence < 0.6
        assert span.ambiguous_between == ("hi", "mr")

    def test_no_speaker_profile_keeps_model_guess_but_still_reports_ambiguity(self) -> None:
        agent = _agent(texts=[self._ambiguous_response()])

        result = agent.identify(_request(raw_text="Aaj nahi", primary_language=None))

        span = result.spans[0]
        assert span.language == "hi"  # the model's own best guess, unchanged
        assert span.fallback_applied is False
        assert span.ambiguous_between == ("hi", "mr")


class TestMalformedResponses:
    def test_missing_language_field_raises(self) -> None:
        response = json.dumps(
            {
                "spans": [{"text": "hi", "start_char": 0, "end_char": 2, "confidence": 0.9}],
                "overall_confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        with pytest.raises(ModelResponseMalformed):
            agent.identify(_request(raw_text="hi", primary_language="en"))

    def test_language_outside_supported_set_raises(self) -> None:
        response = json.dumps(
            {
                "spans": [
                    {
                        "text": "bonjour",
                        "start_char": 0,
                        "end_char": 7,
                        "language": "fr",
                        "confidence": 0.9,
                        "ambiguous_between": [],
                    }
                ],
                "overall_confidence": 0.9,
            }
        )
        agent = _agent(texts=[response])
        with pytest.raises(ModelResponseMalformed):
            agent.identify(_request(raw_text="bonjour", primary_language="en"))

    def test_empty_spans_raises(self) -> None:
        response = json.dumps({"spans": [], "overall_confidence": 0.9})
        agent = _agent(texts=[response])
        with pytest.raises(ModelResponseMalformed):
            agent.identify(_request(raw_text="hi", primary_language="en"))


def test_agent_id_is_a64() -> None:
    assert str(AGENT_ID) == "A64"


def test_a64_never_on_pro_tier_allowlist() -> None:
    """A64 is Flash-only (spec §15.11) — it must never be permitted to
    request Pro-tier."""
    assert AGENT_ID not in PRO_TIER_ALLOWLIST
