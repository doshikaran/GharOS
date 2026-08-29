"""`VertexTtsClient` — the real, live-verified TTS path for A69 Voice
Response Agent (spec §14.7/§15.11, PHASES.md Phase 13).

**Which real TTS path this project uses, and why (the honesty discipline
this project used for Phase 6's browser-paint caveat and Phase 10's
real-vs-sandbox disclosure):** a live Vertex AI Gemini native
audio-output call was tried FIRST, per this phase's own dispatch
instruction — `google.genai`'s `generate_content` with
`response_modalities=["AUDIO"]` against `gemini-2.5-flash-preview-tts`.
It genuinely works: a real live call this phase (against the same
`blissful-trail-506312-t0` project ADR-010/ADR-017's own live tests use),
`location="global"` (the `preview-tts` model 404s regionally in
`asia-south1` for this project, exactly the same regional Model Garden
gap ADR-010 already documents for `gemini-2.5-pro` — resolved the same
way, via the `"global"` location), returned real PCM16 24kHz audio
(`audio/L16;codec=pcm;rate=24000`) for real English, Hindi, Marathi, and
Spanish input text, each confirmed by a real, separate live call this
phase (not assumed from documentation). **The separate Cloud Text-to-
Speech API was never needed** — the honest fallback path spec anticipated
turned out not to be required, because the primary path genuinely works
in this project. This is stated plainly here, not implied: no
`google-cloud-texttospeech` import exists anywhere in this file or this
package.

**A real, load-bearing detail from that verification, not assumed:** a
bare `response_modalities=["AUDIO"]` config alone returns
`400 INVALID_ARGUMENT` on this model — a `types.SpeechConfig` with a
`prebuilt_voice_config.voice_name` set is required. `types.SpeechConfig`
(this project's installed `google-genai` SDK version) exposes only
`voice_config` / `language_code` / `multi_speaker_voice_config` — no
rate/pitch/SSML field at all (confirmed by direct field introspection
this phase) — which is why `pacing.py`'s `PacingProfile.style_instruction`
is a natural-language prefix on the text itself, the only real control
surface this SDK version exposes, not a dedicated parameter this module
could set instead.

Dependency-injected `client_factory`, mirroring `reasoning.model_router.
ModelRouter`'s own pattern exactly: no module-level singleton holding the
`genai.Client`, and a test can supply a fake without real GCP credentials.
This module deliberately does NOT route through `reasoning.model_router.
ModelRouter` — that module's Flash/Pro allowlist governs *text-reasoning*
model calls (`gemini_model_flash`/`gemini_model_pro`), and the TTS model
used here is a third, distinct model that generates audio, not text; the
Pro-tier allowlist check that gates `A69`'s own *text* response-generation
call (via `reasoning.gemini_client.GeminiClient.generate_structured`,
`ModelTier.PRO`) is unaffected and unchanged by this module's existence.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog
from google import genai
from google.genai import types

from .errors import TtsCallFailed

logger = structlog.get_logger(__name__)

DEFAULT_TTS_MODEL = "gemini-2.5-flash-preview-tts"
"""Live-verified this phase (module docstring) — a real audio response for
all four spec §14.2 languages using one shared prebuilt voice."""

DEFAULT_TTS_LOCATION = "global"
"""The `preview-tts` model family 404s regionally in `asia-south1` for
this project (confirmed live, same finding class as ADR-010's Pro-tier
gap) — `"global"` is where it actually resolves."""

TtsClientFactory = Callable[[str, str], genai.Client]
"""Builds a `google.genai.Client` given `(project_id, location)` — same
shape as `reasoning.model_router.ClientFactory`, independently defined
here since this module deliberately does not import `ModelRouter` (see
module docstring)."""


def _default_client_factory(project_id: str, location: str) -> genai.Client:
    return genai.Client(vertexai=True, project=project_id, location=location)


@dataclass(frozen=True, slots=True)
class TtsAudio:
    """One completed, successful TTS synthesis — never constructed for a
    failed or empty response (a failed call always raises `errors.
    TtsCallFailed` instead — safety invariant #7's analogue here)."""

    data: bytes
    mime_type: str


class VertexTtsClient:
    """Thin wrapper around a live Vertex AI Gemini native audio-output
    call. Dependency-injected per gharos-standards: holds no module-level
    singleton; every call resolves a fresh `genai.Client` via the injected
    `client_factory`.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str = DEFAULT_TTS_LOCATION,
        model_name: str = DEFAULT_TTS_MODEL,
        client_factory: TtsClientFactory = _default_client_factory,
    ) -> None:
        self._project_id = project_id
        self._location = location
        self._model_name = model_name
        self._client_factory = client_factory

    def synthesize(self, *, text: str, voice_name: str, language_code: str) -> TtsAudio:
        """Synthesizes `text` to real audio.

        Args:
            text: the exact text to speak — already fully composed
                (style instruction and all) by the caller
                (`voice_response_agent.py`); this method performs no
                further phrasing of its own.
            voice_name: a prebuilt Gemini TTS voice name (e.g. `"Kore"`,
                live-verified this phase).
            language_code: a BCP-47 tag (`pacing.language_code_for`).

        Returns:
            A `TtsAudio` with the real bytes and the real MIME type
            Vertex AI reported — never coerced to a caller-assumed shape.

        Raises:
            errors.TtsCallFailed: the underlying call raised, or returned
                a response with no audio part at all — never silently
                reinterpreted as an empty success.
        """
        client = self._client_factory(self._project_id, self._location)
        config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
                ),
                language_code=language_code,
            ),
        )
        try:
            response = client.models.generate_content(model=self._model_name, contents=text, config=config)
        except Exception as exc:  # noqa: BLE001 — tool boundary; converted to a typed error below.
            logger.warning(
                "voice.tts_client.call_failed", model_name=self._model_name, reason=str(exc)
            )
            raise TtsCallFailed(model_name=self._model_name, reason=str(exc)) from exc

        candidates = response.candidates
        if not candidates or not candidates[0].content or not candidates[0].content.parts:
            raise TtsCallFailed(model_name=self._model_name, reason="response contained no candidate parts")

        for part in candidates[0].content.parts:
            inline_data = getattr(part, "inline_data", None)
            if inline_data is not None and inline_data.data:
                logger.info(
                    "voice.tts_client.synthesized",
                    model_name=self._model_name,
                    mime_type=inline_data.mime_type,
                    size_bytes=len(inline_data.data),
                )
                return TtsAudio(data=inline_data.data, mime_type=inline_data.mime_type or "audio/L16")

        raise TtsCallFailed(model_name=self._model_name, reason="response contained no inline audio data")


__all__ = ["DEFAULT_TTS_LOCATION", "DEFAULT_TTS_MODEL", "TtsAudio", "TtsClientFactory", "VertexTtsClient"]
