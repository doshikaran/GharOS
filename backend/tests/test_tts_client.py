"""Tests for `app.voice.tts_client.VertexTtsClient` — the real TTS path
verified live this phase (PHASES.md Phase 13, ADR-020) — see that
module's own docstring for the full verification detail.

Unit tests inject a fake `genai.Client` (mirrors `reasoning.model_router`
/ `reasoning.gemini_client`'s own test doubles, independently defined here
since this module deliberately does not import `ModelRouter`); four real
live tests (gated the same way `test_gemini_client.py`'s own live tests
are) prove a real call synthesizes real audio for all four spec §14.2
languages — this is literally the exact call this phase's own live
verification used to decide the TTS architecture, kept as a permanent,
re-runnable regression proof rather than a one-off throwaway script.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from google import genai

from app.voice.errors import TtsCallFailed
from app.voice.tts_client import DEFAULT_TTS_LOCATION, DEFAULT_TTS_MODEL, VertexTtsClient

_PROJECT_ID = "gharos-test-project"


class _FakeInlineData:
    def __init__(self, data: bytes, mime_type: str) -> None:
        self.data = data
        self.mime_type = mime_type


class _FakePart:
    def __init__(self, inline_data: _FakeInlineData | None) -> None:
        self.inline_data = inline_data


class _FakeContent:
    def __init__(self, parts: list[_FakePart]) -> None:
        self.parts = parts


class _FakeCandidate:
    def __init__(self, content: _FakeContent | None) -> None:
        self.content = content


class _FakeResponse:
    def __init__(self, candidates: list[_FakeCandidate]) -> None:
        self.candidates = candidates


class _FakeModels:
    def __init__(self, response: _FakeResponse | None = None, error: Exception | None = None) -> None:
        self._response = response
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: object, config: object = None) -> _FakeResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._error is not None:
            raise self._error
        assert self._response is not None
        return self._response


class _FakeGenaiClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _client_with(fake_models: _FakeModels) -> VertexTtsClient:
    def factory(project_id: str, location: str) -> genai.Client:
        return cast(genai.Client, _FakeGenaiClient(fake_models))

    return VertexTtsClient(project_id=_PROJECT_ID, client_factory=factory)


class TestSynthesizeHappyPath:
    def test_returns_real_audio_bytes_and_mime_type(self) -> None:
        fake_models = _FakeModels(
            response=_FakeResponse(
                candidates=[
                    _FakeCandidate(
                        content=_FakeContent(
                            parts=[_FakePart(inline_data=_FakeInlineData(b"\x00\x01\x02", "audio/L16"))]
                        )
                    )
                ]
            )
        )
        client = _client_with(fake_models)

        audio = client.synthesize(text="hello", voice_name="Kore", language_code="en-US")

        assert audio.data == b"\x00\x01\x02"
        assert audio.mime_type == "audio/L16"
        assert fake_models.calls[0]["model"] == DEFAULT_TTS_MODEL


class TestSynthesizeFailureNeverFabricatesSuccess:
    def test_underlying_exception_raises_tts_call_failed(self) -> None:
        fake_models = _FakeModels(error=RuntimeError("boom"))
        client = _client_with(fake_models)
        with pytest.raises(TtsCallFailed):
            client.synthesize(text="hello", voice_name="Kore", language_code="en-US")

    def test_response_with_no_audio_part_raises_tts_call_failed(self) -> None:
        fake_models = _FakeModels(
            response=_FakeResponse(candidates=[_FakeCandidate(content=_FakeContent(parts=[]))])
        )
        client = _client_with(fake_models)
        with pytest.raises(TtsCallFailed):
            client.synthesize(text="hello", voice_name="Kore", language_code="en-US")

    def test_empty_candidates_raises_tts_call_failed(self) -> None:
        fake_models = _FakeModels(response=_FakeResponse(candidates=[]))
        client = _client_with(fake_models)
        with pytest.raises(TtsCallFailed):
            client.synthesize(text="hello", voice_name="Kore", language_code="en-US")


_LIVE_TESTS_ENABLED = os.environ.get("GHAROS_RUN_LIVE_GCP_TESTS") == "1"
_LIVE_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")

_LIVE_TEXTS = {
    "en-US": "Namaste, GharOS is listening.",
    "hi-IN": "Aarav ko Friday ko field trip hai, permission slip sign karna hai.",
    "mr-IN": "Society maintenance cha payment kela ahe.",
    "es-US": "La cita con el dentista es el martes a las tres.",
}


@pytest.mark.live_gcp
@pytest.mark.skipif(
    not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID,
    reason="live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID to run a real TTS call",
)
@pytest.mark.parametrize("language_code,text", sorted(_LIVE_TEXTS.items()))
def test_real_tts_call_synthesizes_real_audio_for_each_supported_language(
    language_code: str, text: str
) -> None:
    """This phase's own live verification, kept as a permanent regression
    test: `gemini-2.5-flash-preview-tts` at `location="global"` genuinely
    returns real audio for all four spec §14.2 languages using one shared
    prebuilt voice ("Kore") — the finding `tts_client.py`'s own module
    docstring reports."""
    client = VertexTtsClient(project_id=_LIVE_PROJECT_ID, location=DEFAULT_TTS_LOCATION)

    audio = client.synthesize(text=text, voice_name="Kore", language_code=language_code)

    assert len(audio.data) > 0
    assert "audio" in audio.mime_type


__all__: list[str] = []
