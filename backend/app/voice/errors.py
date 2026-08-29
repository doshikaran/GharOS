"""Typed errors local to `backend/app/voice/` (A62, A63, A66, A69).

`contracts/errors.py` is frozen and CTO-owned; `app.reasoning.errors.
GeminiCallFailed` and `app.agents.voice.errors.ModelResponseMalformed`
(E2's own package) are reused directly wherever they apply — this module
covers failure modes specific to the infrastructure agents in this
package that do not fit either of those (mirrors the precedent
`app.agents.voice.errors` / `app.arbitration.errors` already set for
their own packages).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations


class VoiceInfraError(Exception):
    """Base class for every typed error raised by `backend/app/voice/`."""


class ConsequentialSpanUnclear(VoiceInfraError):
    """Raised by A63 (`speech_recognition_handler.py`) when a token whose
    text looks money/date/name-shaped (a real, if heuristic, signal — see
    that module's docstring) remains below its confidence floor. Spec's
    own A63 failure mode: "low confidence on consequential tokens forces
    clarification" — this is the structural proof that A63 never guesses
    on such a token. The caller (`session_manager.VoiceSessionManager`)
    must re-prompt the household member for clarification and must never
    act on `partial_raw_text`.
    """

    def __init__(self, *, turn_id: str, span_text: str, confidence: float) -> None:
        self.turn_id = turn_id
        self.span_text = span_text
        self.confidence = confidence
        super().__init__(
            f"turn {turn_id!r}: consequential-shaped span {span_text!r} has confidence "
            f"{confidence:.2f} — forcing clarification rather than guessing"
        )


class TtsCallFailed(VoiceInfraError):
    """Raised when a live Vertex AI Gemini TTS (audio-output) call fails or
    returns no audio — the only acceptable way `tts_client.VertexTtsClient`
    reports a failed synthesis call (safety invariant #7's analogue here:
    a failed synthesis is never reinterpreted as silent success)."""

    def __init__(self, *, model_name: str, reason: str) -> None:
        self.model_name = model_name
        self.reason = reason
        super().__init__(f"TTS call failed on model '{model_name}': {reason}")


class SessionCorrupted(VoiceInfraError):
    """Raised (and caught by the session manager's own turn loop, never by
    a caller) when a turn cannot be completed cleanly — a WebSocket
    disconnect mid-turn, an unreadable audio chunk, or a pipeline stage
    that raised an exception this module's own turn handler cannot
    otherwise attribute to a specific, user-facing clarification. Spec's
    own A62 failure mode: "session corruption -> close cleanly, re-prompt,
    never act on a partial turn." A corrupted turn is discarded in full —
    no partial `VoiceIntentResult`/`NormalizationResult` from it is ever
    passed to the Approval Gate or any execution callback.
    """

    def __init__(self, *, turn_id: str, reason: str) -> None:
        self.turn_id = turn_id
        self.reason = reason
        super().__init__(f"turn {turn_id!r} corrupted, discarding: {reason}")


__all__ = [
    "ConsequentialSpanUnclear",
    "SessionCorrupted",
    "TtsCallFailed",
    "VoiceInfraError",
]
