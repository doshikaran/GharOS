"""Tests for the demo-mode deterministic TTS path (PHASES.md Phase 15 —
"flaky external calls cached or sandboxed").

`app.voice.tts_client.DeterministicTtsClient` is what stands in for the
live Vertex AI Gemini audio-output call during the on-camera voice beat
(spec §24, 2:20) so a transient 5xx or latency spike on that call cannot
break the run. The contract these tests pin:

  1. `create_tts_client` returns the deterministic client for `ENV=demo`
     and ONLY for `ENV=demo` — every other env keeps the real path.
  2. The deterministic client is byte-for-byte reproducible: identical
     inputs -> identical audio bytes, across independent instances.
  3. Different inputs -> different bytes (text, voice, or language).
  4. The output shape matches the real client's (`TtsAudio` with real
     PCM16 mono bytes at the same rate/MIME) so nothing downstream can
     tell the two apart structurally.
"""

from __future__ import annotations

import pytest

from app.voice.tts_client import (
    DETERMINISTIC_TTS_MIME_TYPE,
    DETERMINISTIC_TTS_RATE_HZ,
    DeterministicTtsClient,
    TtsAudio,
    VertexTtsClient,
    create_tts_client,
)

_PROJECT_ID = "gharos-test-project"
_LINE = "Aarav ko Friday ko field trip hai, permission slip sign karna hai."


@pytest.mark.parametrize("env", ["demo", "DEMO", " Demo ", "demo\n"])
def test_create_tts_client_returns_deterministic_for_demo_env(env: str) -> None:
    client = create_tts_client(env=env, project_id=_PROJECT_ID)
    assert isinstance(client, DeterministicTtsClient)


@pytest.mark.parametrize("env", ["production", "staging", "local", "", "prod", "demoish"])
def test_create_tts_client_returns_real_client_for_every_other_env(env: str) -> None:
    client = create_tts_client(env=env, project_id=_PROJECT_ID)
    assert isinstance(client, VertexTtsClient)


def test_deterministic_client_is_byte_for_byte_reproducible() -> None:
    first = DeterministicTtsClient().synthesize(text=_LINE, voice_name="Kore", language_code="hi-IN")
    second = DeterministicTtsClient().synthesize(text=_LINE, voice_name="Kore", language_code="hi-IN")
    assert isinstance(first, TtsAudio)
    assert first.data == second.data
    assert first.mime_type == second.mime_type == DETERMINISTIC_TTS_MIME_TYPE
    assert len(first.data) > 0
    # PCM16 mono -> an even number of bytes, and a plausible duration
    # (0.4s floor .. 6.0s ceiling) at the declared rate.
    assert len(first.data) % 2 == 0
    samples = len(first.data) // 2
    assert DETERMINISTIC_TTS_RATE_HZ * 0.4 <= samples <= DETERMINISTIC_TTS_RATE_HZ * 6.0


def test_deterministic_client_output_varies_with_every_input_axis() -> None:
    base = DeterministicTtsClient().synthesize(text=_LINE, voice_name="Kore", language_code="hi-IN")
    changed_text = DeterministicTtsClient().synthesize(
        text=_LINE + " Aur ek baat.", voice_name="Kore", language_code="hi-IN"
    )
    changed_voice = DeterministicTtsClient().synthesize(text=_LINE, voice_name="Puck", language_code="hi-IN")
    changed_lang = DeterministicTtsClient().synthesize(text=_LINE, voice_name="Kore", language_code="mr-IN")
    variants = {base.data, changed_text.data, changed_voice.data, changed_lang.data}
    assert len(variants) == 4  # every axis independently changes the bytes


def test_deterministic_client_makes_no_external_call_and_never_raises() -> None:
    # No genai.Client, no project id, no network — the whole reason the
    # demo path uses it. A trivially short and a long line both succeed.
    for text in ("Yes.", _LINE * 40):
        audio = DeterministicTtsClient().synthesize(text=text, voice_name="Kore", language_code="en-IN")
        assert isinstance(audio, TtsAudio)
        assert len(audio.data) % 2 == 0
