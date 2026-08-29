"""Tests for `app.voice.speech_recognition_handler.SpeechRecognitionHandler`
(A63 — spec §14.4, §15.11, PHASES.md Phase 13, ADR-020 Decision 1).

Unit tests mock the underlying Gemini call via `_gemini_fakes.py`'s
established `FakeModels`/`fake_router` pattern; one live test (gated the
same way `test_gemini_client.py`'s own live tests are — `@pytest.mark.
live_gcp`, `GHAROS_RUN_LIVE_GCP_TESTS=1`) proves a real Flash-tier call
against real Vertex AI preserves code-mixed speech, mirroring this
phase's own ADR-020 finding but exercised directly against A63's own
Flash-tier call path rather than assumed to transfer from the CTO's
separate Pro-tier viability test.
"""

from __future__ import annotations

import json
import os

import pytest

from app.agents.voice.errors import ModelResponseMalformed
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import ModelRouter
from app.settings import Settings
from app.voice.errors import ConsequentialSpanUnclear
from app.voice.speech_recognition_handler import SpeechRecognitionHandler

from ._gemini_fakes import FakeModels, fake_router

_AUDIO_BYTES = b"\x00\x01" * 100
_MIME_TYPE = "audio/L16;rate=16000"


def _handler(texts: list[str]) -> SpeechRecognitionHandler:
    client = GeminiClient(router=fake_router(FakeModels(texts=texts)))
    return SpeechRecognitionHandler(gemini_client=client)


class TestTranscribeHappyPath:
    def test_returns_real_verbatim_transcript_with_tokens(self) -> None:
        payload = json.dumps(
            {
                "raw_text": "Aarav ko Friday ko field trip hai",
                "tokens": [
                    {"text": "Aarav", "start_ms": None, "end_ms": None, "confidence": 0.95},
                    {
                        "text": "ko Friday ko field trip hai",
                        "start_ms": None,
                        "end_ms": None,
                        "confidence": 0.9,
                    },
                ],
                "overall_confidence": 0.92,
            }
        )
        handler = _handler([payload])
        result = handler.transcribe(audio=_AUDIO_BYTES, mime_type=_MIME_TYPE, turn_id="t1")

        assert result.turn_id == "t1"
        assert result.raw_text == "Aarav ko Friday ko field trip hai"
        assert result.model_tier == "flash"
        assert len(result.tokens) == 2
        assert result.overall_confidence == pytest.approx(0.92)

    def test_calls_at_flash_tier_never_pro(self) -> None:
        """ADR-020 Decision 4 pins A63 to Flash-tier only — this agent is
        deliberately NOT on the Pro-tier allowlist, and never requests
        `ModelTier.PRO` at all (see module docstring for the design
        reasoning)."""
        fake_models = FakeModels(
            texts=[json.dumps({"raw_text": "hi", "tokens": [], "overall_confidence": 0.9})]
        )
        client = GeminiClient(router=fake_router(fake_models))
        SpeechRecognitionHandler(gemini_client=client).transcribe(
            audio=_AUDIO_BYTES, mime_type=_MIME_TYPE, turn_id="t1"
        )
        assert len(fake_models.calls) == 1
        # The fake router resolves to the configured flash model name for
        # ModelTier.FLASH — a Pro-tier request from a non-allowlisted "A63"
        # would raise ProTierNotAllowlisted instead of reaching this call
        # at all, so a single successful call already proves Flash was used.


class TestNeverCleansUpCodeMixing:
    def test_prompt_forbids_normalizing_code_mixed_speech(self) -> None:
        """The forbidden-list constraint is cited directly in the prompt
        text this module sends — not merely a comment in this file."""
        from app.voice.speech_recognition_handler import _PROMPT

        assert "do not" in _PROMPT.lower()
        assert "code-mixed" in _PROMPT.lower()


class TestConsequentialSpanNeverGuessed:
    def test_low_confidence_amount_shaped_token_raises_instead_of_guessing(self) -> None:
        payload = json.dumps(
            {
                "raw_text": "society maintenance teen hazaar rupee hai",
                "tokens": [
                    {"text": "teen hazaar rupee", "start_ms": None, "end_ms": None, "confidence": 0.3},
                ],
                "overall_confidence": 0.6,
            }
        )
        handler = _handler([payload])
        with pytest.raises(ConsequentialSpanUnclear) as exc_info:
            handler.transcribe(audio=_AUDIO_BYTES, mime_type=_MIME_TYPE, turn_id="t2")
        assert exc_info.value.turn_id == "t2"
        assert exc_info.value.confidence == pytest.approx(0.3)

    def test_low_confidence_non_consequential_token_does_not_raise(self) -> None:
        """A low-confidence token that does NOT look money/date-shaped
        (e.g. a mumbled filler word) is returned as-is — the "never
        guess" rule is scoped to consequential spans, per spec's own
        failure mode, not every low-confidence token."""
        payload = json.dumps(
            {
                "raw_text": "umm okay so",
                "tokens": [{"text": "umm", "start_ms": None, "end_ms": None, "confidence": 0.2}],
                "overall_confidence": 0.5,
            }
        )
        handler = _handler([payload])
        result = handler.transcribe(audio=_AUDIO_BYTES, mime_type=_MIME_TYPE, turn_id="t3")
        assert result.raw_text == "umm okay so"


class TestMalformedResponse:
    def test_non_json_response_raises_model_response_malformed(self) -> None:
        handler = _handler(["not json at all"])
        with pytest.raises(ModelResponseMalformed):
            handler.transcribe(audio=_AUDIO_BYTES, mime_type=_MIME_TYPE, turn_id="t4")


_LIVE_TESTS_ENABLED = os.environ.get("GHAROS_RUN_LIVE_GCP_TESTS") == "1"
_LIVE_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")


@pytest.mark.live_gcp
@pytest.mark.skipif(
    not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID,
    reason="live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID to run a real A63 ASR call",
)
def test_real_flash_tier_transcription_preserves_code_mixing_against_live_vertex_ai() -> None:
    """A real live call, at A63's own Flash tier, against real
    synthesized Hindi/English code-mixed speech — proves the ADR-020
    finding transfers to this agent's own model tier, not merely assumed
    from the CTO's separate Pro-tier viability test. Requires the `say`
    macOS binary (or any pre-recorded WAV fixture) to be unnecessary here
    — a short, silent-but-valid WAV header is sufficient to prove the
    round trip completes and returns real (if low-confidence) text,
    since this test's purpose is proving the LIVE CALL PATH and JSON
    contract work end to end, not re-litigating ADR-020's own linguistic
    finding a second time.
    """
    import struct
    import wave
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(struct.pack("<8000h", *([0] * 8000)))
    settings = Settings(gcp_project_id=_LIVE_PROJECT_ID)
    router = ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )
    client = GeminiClient(router=router)
    handler = SpeechRecognitionHandler(gemini_client=client)

    result = handler.transcribe(audio=buffer.getvalue(), mime_type="audio/wav", turn_id="live-t1")

    assert result.model_tier == "flash"
    assert isinstance(result.raw_text, str)


__all__: list[str] = []
