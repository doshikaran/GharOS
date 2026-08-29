"""Tests for `app.voice.voice_response_agent.VoiceResponseAgent` (A69 —
spec §14.7, §15.11, PHASES.md Phase 13, ADR-020 Decision 4).

**Cross-role wiring note (mirrors `test_confidence_arbiter.py`'s own
documented technique for A57's identical situation):** a real Pro-tier
text-composition call requires `AgentId("A69")` on `app.reasoning.
model_router.PRO_TIER_ALLOWLIST` — that module is E2-owned and this
phase's E3 work does not edit it. ADR-020 Decision 4 assigns adding it
there to E2; as of this phase's E3 hand-off it had not yet landed
(confirmed by reading the file directly). Every test below `monkeypatch`s
the allowlist for its own duration only, proving this agent's own logic
correct independent of that cross-role gap — see the final report for the
one-line change E2 needs to land.
"""

from __future__ import annotations

import json

import pytest

from app.reasoning import model_router as model_router_module
from app.reasoning.gemini_client import GeminiClient
from app.voice.tts_client import TtsAudio
from app.voice.types import PacingProfile, ResponseRequest
from app.voice.voice_response_agent import AGENT_ID, VoiceResponseAgent

from ._gemini_fakes import FakeModels, fake_router


@pytest.fixture(autouse=True)
def _allow_a69_pro_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        model_router_module, "PRO_TIER_ALLOWLIST", model_router_module.PRO_TIER_ALLOWLIST | {AGENT_ID}
    )


class _FakeTtsClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def synthesize(self, *, text: str, voice_name: str, language_code: str) -> TtsAudio:
        self.calls.append({"text": text, "voice_name": voice_name, "language_code": language_code})
        return TtsAudio(data=b"\x00\x01", mime_type="audio/L16;codec=pcm;rate=24000")


_DEFAULT_PACING = PacingProfile(
    style_instruction="In a warm, natural, conversational pace", language_code="en-US"
)


def _agent(texts: list[str]) -> tuple[VoiceResponseAgent, _FakeTtsClient]:
    gemini_client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    tts_client = _FakeTtsClient()
    return VoiceResponseAgent(gemini_client=gemini_client, tts_client=tts_client), tts_client


class TestRespondHappyPath:
    def test_returns_real_spoken_text_and_real_audio(self) -> None:
        payload = json.dumps({"spoken_text": "Okay, I've noted that.", "confidence": 0.9})
        agent, tts = _agent([payload])
        request = ResponseRequest(
            turn_id="t1",
            speaker_language="en",
            content_summary="acknowledge the school trip permission slip is signed",
            response_kind="acknowledgement",
            pacing=_DEFAULT_PACING,
        )

        result = agent.respond(request)

        assert result.spoken_text == "Okay, I've noted that."
        assert result.audio_bytes == b"\x00\x01"
        assert result.model_tier == "pro"
        assert tts.calls[0]["voice_name"] == "Kore"
        assert tts.calls[0]["language_code"] == "en-US"
        assert "In a warm, natural, conversational pace" in tts.calls[0]["text"]


class TestListEnumerationCap:
    def test_fewer_than_three_items_are_all_shown_to_the_model(self) -> None:
        payload = json.dumps({"spoken_text": "You have two things due.", "confidence": 0.9})
        agent, _ = _agent([payload])
        request = ResponseRequest(
            turn_id="t2",
            speaker_language="en",
            content_summary="summarise open obligations",
            response_kind="answer",
            pacing=_DEFAULT_PACING,
            list_items=("Pay society dues", "Sign permission slip"),
        )
        result = agent.respond(request)
        assert result.deferred_full_list is False

    def test_three_or_more_items_defers_and_caps_at_two_shown(self) -> None:
        """Spec's own A69 forbidden list: "reading long lists aloud" —
        enforced structurally, not just by prompt wording. The full list
        is never sent to the model at all once capped."""
        payload = json.dumps({"spoken_text": "You have a few things due — check the app.", "confidence": 0.9})
        agent, _ = _agent([payload])
        request = ResponseRequest(
            turn_id="t3",
            speaker_language="en",
            content_summary="summarise open obligations",
            response_kind="answer",
            pacing=_DEFAULT_PACING,
            list_items=("Pay society dues", "Sign permission slip", "Renew insurance", "Book dentist"),
        )
        result = agent.respond(request)
        assert result.deferred_full_list is True

    def test_capped_prompt_never_contains_the_deferred_items_verbatim(self) -> None:
        payload = json.dumps({"spoken_text": "A few things — check the app.", "confidence": 0.9})
        fake_models = FakeModels(texts=[payload])
        gemini_client = GeminiClient(router=fake_router(fake_models))
        tts_client = _FakeTtsClient()
        agent = VoiceResponseAgent(gemini_client=gemini_client, tts_client=tts_client)
        request = ResponseRequest(
            turn_id="t4",
            speaker_language="en",
            content_summary="summarise open obligations",
            response_kind="answer",
            pacing=_DEFAULT_PACING,
            list_items=("Item A", "Item B", "Item C — never shown", "Item D — never shown"),
        )
        agent.respond(request)

        # Inspect the actual prompt text sent to the model — the deferred
        # items must never appear in it at all, structurally, not merely
        # "the model was told not to say them."
        prompt_sent = str(fake_models.calls[0]["contents"])
        assert "Item A" in prompt_sent
        assert "Item B" in prompt_sent
        assert "Item C" not in prompt_sent
        assert "Item D" not in prompt_sent


class TestPacingStyleShapesTheAudioRequest:
    def test_style_instruction_is_prefixed_onto_the_tts_text(self) -> None:
        payload = json.dumps({"spoken_text": "Done.", "confidence": 0.9})
        agent, tts = _agent([payload])
        elder_pacing = PacingProfile(
            style_instruction="Slowly, clearly, and gently, with a distinct pause between each sentence",
            language_code="hi-IN",
        )
        request = ResponseRequest(
            turn_id="t5",
            speaker_language="hi",
            content_summary="acknowledge",
            response_kind="acknowledgement",
            pacing=elder_pacing,
        )
        agent.respond(request)
        assert tts.calls[0]["text"].startswith("Slowly, clearly, and gently")
        assert tts.calls[0]["language_code"] == "hi-IN"


__all__: list[str] = []
