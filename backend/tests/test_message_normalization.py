"""Tests for A4 Message Normalization Agent
(`app.agents.intake.message_normalization`).

spec §15.2 A4: WhatsApp/SMS/app notifications -> normalized events,
multi-language and code-mixed tolerant, Flash only, forbidden: action,
implication. Central assertion: code-mixed text is never "cleaned up" —
`original_text` is always the verbatim source.
"""

from __future__ import annotations

import json

from contracts.agents import ModelTier

from app.agents.intake.message_normalization import MessageEventType, MessageNormalizationAgent
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(response_obj: dict[str, object]) -> MessageNormalizationAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return MessageNormalizationAgent(gemini_client=client)


CODE_MIXED_TEXT = "Kal mummy ko doctor ke paas le jaana hai, I'll book the slot."


class TestMessageNormalization:
    def test_code_mixed_text_preserved_verbatim(self) -> None:
        agent = _agent(
            {
                "events": [
                    {
                        "speaker": "Priya",
                        "original_text": CODE_MIXED_TEXT,
                        "event_type": "commitment",
                        "language_note": "romanized Hindi + English, code-mixed",
                        "confidence": 0.85,
                    }
                ]
            }
        )
        result = agent.normalize(transcript=f"10:00 Priya: {CODE_MIXED_TEXT}")

        assert len(result.events) == 1
        assert result.events[0].original_text == CODE_MIXED_TEXT
        assert "code-mixed" in result.events[0].language_note

    def test_commitment_classified_correctly(self) -> None:
        agent = _agent(
            {
                "events": [
                    {
                        "speaker": "Dad",
                        "original_text": "I'll pick her up Friday",
                        "event_type": "commitment",
                        "language_note": "English only",
                        "confidence": 0.9,
                    }
                ]
            }
        )
        result = agent.normalize(transcript="09:00 Dad: I'll pick her up Friday")
        assert result.events[0].event_type is MessageEventType.COMMITMENT

    def test_uses_flash_tier_only(self) -> None:
        agent = _agent({"events": []})
        result = agent.normalize(transcript="empty")
        assert result.agent_output.model_tier is ModelTier.FLASH

    def test_multiple_events_from_one_transcript(self) -> None:
        agent = _agent(
            {
                "events": [
                    {
                        "speaker": "Mom",
                        "original_text": "leave lunga kal",
                        "event_type": "leave_notification",
                        "language_note": "romanized Hindi",
                        "confidence": 0.8,
                    },
                    {
                        "speaker": "Mom",
                        "original_text": "the maid keeps coming late",
                        "event_type": "complaint",
                        "language_note": "English",
                        "confidence": 0.75,
                    },
                ]
            }
        )
        result = agent.normalize(transcript="whatever")
        assert len(result.events) == 2
        assert {e.event_type for e in result.events} == {
            MessageEventType.LEAVE_NOTIFICATION,
            MessageEventType.COMPLAINT,
        }
