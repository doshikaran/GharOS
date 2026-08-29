"""Tests for `app.voice.speaker_identification.SpeakerIdentificationAgent`
(A66 — spec §14.4, §15.11, PHASES.md Phase 13, ADR-020).
"""

from __future__ import annotations

import json

import pytest
from contracts.graph_types import NodeId

from app.reasoning.gemini_client import GeminiClient
from app.voice.speaker_identification import SpeakerIdentificationAgent
from app.voice.types import EnrolledSpeaker

from ._gemini_fakes import FakeModels, fake_router

_TURN_AUDIO = b"\x01\x02" * 50
_TURN_MIME = "audio/L16;rate=16000"


def _speaker(person_id: str, name: str) -> EnrolledSpeaker:
    return EnrolledSpeaker(
        person_id=NodeId(person_id),
        display_name=name,
        reference_audio=b"\x00\x00" * 50,
        reference_mime_type=_TURN_MIME,
    )


def _agent(texts: list[str]) -> SpeakerIdentificationAgent:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return SpeakerIdentificationAgent(gemini_client=client)


class TestRealComparisonPerCandidate:
    def test_makes_one_comparison_call_per_enrolled_speaker(self) -> None:
        fake_models = FakeModels(
            texts=[
                json.dumps({"same_speaker": False, "confidence": 0.2, "reasoning": "different pitch"}),
                json.dumps({"same_speaker": True, "confidence": 0.9, "reasoning": "matches"}),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = SpeakerIdentificationAgent(gemini_client=client)

        result = agent.identify(
            turn_audio=_TURN_AUDIO,
            turn_mime_type=_TURN_MIME,
            enrolled_speakers=(_speaker("person-1", "Priya"), _speaker("person-2", "Aarav")),
        )

        assert len(fake_models.calls) == 2
        assert result.person_id == NodeId("person-2")
        assert result.display_name == "Aarav"
        assert result.confidence == pytest.approx(0.9)
        assert result.matched_against_person_ids == (NodeId("person-1"), NodeId("person-2"))


class TestUnknownSpeakerNeverGuesses:
    def test_no_match_above_floor_returns_unknown(self) -> None:
        fake_models = FakeModels(
            texts=[json.dumps({"same_speaker": True, "confidence": 0.4, "reasoning": "maybe"})]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = SpeakerIdentificationAgent(gemini_client=client)

        result = agent.identify(
            turn_audio=_TURN_AUDIO,
            turn_mime_type=_TURN_MIME,
            enrolled_speakers=(_speaker("person-1", "Priya"),),
        )

        assert result.person_id is None
        assert result.display_name is None
        assert result.matched_against_person_ids == (NodeId("person-1"),)

    def test_zero_enrolled_speakers_is_a_real_unknown_speaker_result_not_a_crash(self) -> None:
        """spec §15.11 A66's own failure mode, exercised at its edge: a
        household with nobody enrolled yet must never crash and must
        never guess an identity."""
        client = GeminiClient(router=fake_router(FakeModels(texts=["{}"])))
        agent = SpeakerIdentificationAgent(gemini_client=client)

        result = agent.identify(turn_audio=_TURN_AUDIO, turn_mime_type=_TURN_MIME, enrolled_speakers=())

        assert result.person_id is None
        assert result.matched_against_person_ids == ()
        assert result.confidence == 0.0


class TestBestMatchWins:
    def test_highest_confidence_match_above_floor_is_selected(self) -> None:
        fake_models = FakeModels(
            texts=[
                json.dumps({"same_speaker": True, "confidence": 0.7, "reasoning": "close"}),
                json.dumps({"same_speaker": True, "confidence": 0.95, "reasoning": "very close"}),
            ]
        )
        client = GeminiClient(router=fake_router(fake_models))
        agent = SpeakerIdentificationAgent(gemini_client=client)

        result = agent.identify(
            turn_audio=_TURN_AUDIO,
            turn_mime_type=_TURN_MIME,
            enrolled_speakers=(_speaker("person-1", "Priya"), _speaker("person-2", "Kaku")),
        )

        assert result.person_id == NodeId("person-2")
        assert result.confidence == pytest.approx(0.95)


__all__: list[str] = []
