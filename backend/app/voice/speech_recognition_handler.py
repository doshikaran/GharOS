"""A63 — Speech Recognition Handler (spec §14.4, §15.11, PHASES.md
Phase 13, ADR-020 Decision 1) — E3's `backend/app/voice/`.

*Responsibility:* turn one turn's real raw audio bytes into a real
transcript with per-segment confidence — the first stage of the inbound
voice pipeline A62 (`session_manager.py`) drives.

**Built on `reasoning.gemini_client.GeminiClient.generate_multimodal`**,
exactly as ADR-020 Decision 1 records: a live ASR-viability test run
before any of this phase's code was written (the CTO's own test, `gemini-
2.5-pro`, `global` location) proved Vertex AI's `generateContent` audio
path preserves intra-sentential Hindi/English/Marathi code-mixing
verbatim rather than collapsing it into fluent monolingual English — the
architectural precondition this whole module depends on. This module
itself calls at **Flash tier** (ADR-020 Decision 4: "A62/A63/A64/A66 stay
Flash-tier... matching spec's own 'Flash realtime'/'Flash' assignments"),
not the Pro-tier model the CTO's own viability test happened to use —
Flash's own code-mixing preservation is exercised directly by this
module's live test (see `backend/tests/test_speech_recognition_handler.py
::test_real_flash_tier_transcription_preserves_code_mixing_against_live_
vertex_ai`), not assumed to transfer from the Pro-tier finding.

**Never "cleans up" code-mixed speech into fluent monolingual text** — a
hard forbidden-list item (spec §15.2/§15.11 A63's own forbidden list:
"'cleaning up' transcripts into fluent monolingual text destroys the
code-mixing signal and hides uncertainty"). The prompt below states this
constraint explicitly, by name, not merely as a comment in this file —
citing the exact rule the model must follow.

**Honest limitation (ADR-020 Decision 1, same disclosure category as
Phase 6's browser-paint caveat):** Vertex AI's `generateContent` audio
path exposes no true acoustic per-token logprobs the way a dedicated
streaming STT API does. Every `TranscriptToken.asr_confidence` this
module produces is a MODEL-SELF-REPORTED, per-segment confidence — the
model is explicitly asked to flag its own uncertain segments. This is
disclosed here, in this docstring, and must never be presented downstream
as acoustic confidence.

**Never-guess discipline on a consequential span (spec's own A63 failure
mode: "low confidence on consequential tokens forces clarification"),
resolved without a Pro-tier escalation:** ADR-020 Decision 4 pins A63 to
Flash-tier only for this phase — it is deliberately not added to
`reasoning.model_router.PRO_TIER_ALLOWLIST` (only A65/A67/A68/A69 are).
Rather than requesting a disallowed Pro-tier escalation (which would
either violate that frozen decision or require a further, unrequested
contracts/allowlist change), this module satisfies the "never guess"
requirement directly: a token whose text looks money/date/name-shaped (a
real, if heuristic, regex signal — see `_looks_consequential`) and whose
self-reported confidence sits below `_CONSEQUENTIAL_CONFIDENCE_FLOOR`
raises `errors.ConsequentialSpanUnclear` immediately, forcing the caller
to re-prompt for clarification rather than ever act on a guessed
transcription of it — mirroring A65/A13's established escalate-or-clarify
discipline elsewhere in this codebase, adapted to Flash-only per this
specific agent's ADR-pinned tier.

*Forbidden:* "cleaning up" code-mixed speech (see above); guessing a
consequential span's text (structurally impossible — see above). Holds no
tool, no import of `app.arbitration` — see
`backend/tests/test_voice_infra_arbitration_boundary.py`.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from app.agents.voice.errors import ModelResponseMalformed
from app.agents.voice.json_utils import parse_json_response, require_float, require_list, require_str
from app.agents.voice.types import TranscriptToken
from app.reasoning.gemini_client import GeminiClient, MediaPart

from .errors import ConsequentialSpanUnclear
from .types import TranscriptionResult

AGENT_ID = AgentId("A63")

_CONSEQUENTIAL_CONFIDENCE_FLOOR = 0.55
"""Below this, a consequential-shaped token's self-reported confidence is
not trusted — `errors.ConsequentialSpanUnclear` is raised rather than
ever returning a guessed transcription for it. Deliberately lower than
`app.agents.voice.language_script_identifier_agent._AMBIGUITY_CONFIDENCE_
FLOOR` (0.6): that floor governs a *fallback* (to the speaker's primary
language, always still returning something); this floor governs a hard
stop (never return a guess for a money/date/name-shaped span at all)."""

_CONSEQUENTIAL_PATTERN = re.compile(
    r"\d|₹|\$|rs\.?|rupee|paisa|hazaar|lakh|crore|thousand|hundred|percent|"
    r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"today|tomorrow|yesterday|kal|aaj|parso|abhi",
    re.IGNORECASE,
)
"""A real, but deliberately heuristic, "does this token look
money/date-shaped" signal — a regex, not an NLP model, catching digits,
currency markers, Hindi/English amount words, and day/relative-date
words. This is not a claim of complete coverage (a name is not caught by
this pattern at all, since names are open-vocabulary and heuristically
undetectable this way) — it is the concrete, testable mechanism behind
this module's "never guess on a consequential span" behaviour for the
sub-case a regex genuinely can catch; A65's own `needs_clarification`
mechanism (downstream, on already-tagged amount spans) is this system's
second, complementary layer of defence for the same concern."""

_PROMPT = """You are the speech recognition stage of a household operating system, transcribing one turn \
of real, spoken household speech.

CRITICAL RULE, never violate it: transcribe VERBATIM, exactly as spoken. Do NOT translate. Do NOT \
normalize code-mixed speech (a mix of Hindi, Marathi, Spanish, and English within the same sentence — \
completely normal in this household) into fluent monolingual text. Cleaning up code-mixed speech into \
fluent monolingual text destroys the code-mixing signal and hides real uncertainty — this is a hard, \
non-negotiable rule for this task, not a style preference.

Segment the speech into short tokens or phrases in the order spoken. For each segment, report your own \
honest self-assessed confidence in the accuracy of that segment's transcription — do not report a \
uniformly high confidence; flag genuinely uncertain segments (mumbled words, background noise, unclear \
numbers or names) with a lower score.

Respond with a single JSON object and nothing else:
{"raw_text": "the full verbatim transcript, code-mixed exactly as spoken",
 "tokens": [{"text": "...", "start_ms": null, "end_ms": null, "confidence": 0.0}],
 "overall_confidence": 0.0}
"""


def _looks_consequential(text: str) -> bool:
    return bool(_CONSEQUENTIAL_PATTERN.search(text))


def _parse_token(raw: object, *, agent_id: AgentId) -> TranscriptToken:
    if not isinstance(raw, dict):
        raise ModelResponseMalformed(
            agent_id=agent_id, reason=f"expected a token object, got {type(raw).__name__}", raw_text=str(raw)
        )
    text = require_str(raw, "text", agent_id=agent_id)
    confidence = require_float(raw, "confidence", agent_id=agent_id)
    start_ms_raw = raw.get("start_ms")
    end_ms_raw = raw.get("end_ms")
    start_ms = int(start_ms_raw) if isinstance(start_ms_raw, int | float) else None
    end_ms = int(end_ms_raw) if isinstance(end_ms_raw, int | float) else None
    return TranscriptToken(text=text, start_ms=start_ms, end_ms=end_ms, asr_confidence=confidence)


class SpeechRecognitionHandler:
    """A63 Speech Recognition Handler. Dependency-injected on a
    `GeminiClient` only — no `GraphReader`, no tool of any kind."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def transcribe(self, *, audio: bytes, mime_type: str, turn_id: str) -> TranscriptionResult:
        """Transcribes one turn's real audio bytes.

        Args:
            audio: real PCM16 audio bytes for this turn (ADR-020 Decision
                3's wire format — binary WebSocket frames concatenated by
                the caller for one turn).
            mime_type: the real MIME type of `audio` (e.g.
                `"audio/L16;rate=16000"` for raw PCM16 16kHz mono, per the
                WebSocket contract).
            turn_id: the session's own turn identifier, carried through
                for tracing and error context.

        Returns:
            A `TranscriptionResult`.

        Raises:
            app.agents.voice.errors.ModelResponseMalformed: the model
                response could not be parsed as the expected JSON shape.
            errors.ConsequentialSpanUnclear: a money/date-shaped token
                remained below `_CONSEQUENTIAL_CONFIDENCE_FLOOR` — the
                caller must re-prompt for clarification, never act on
                this exception's own partial data.
        """
        call_result = self._gemini_client.generate_multimodal(
            agent_id=AGENT_ID,
            tier=ModelTier.FLASH,
            prompt=_PROMPT,
            media=(MediaPart(data=audio, mime_type=mime_type),),
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_text = require_str(parsed, "raw_text", agent_id=AGENT_ID)
        raw_tokens = require_list(parsed, "tokens", agent_id=AGENT_ID)
        tokens = tuple(_parse_token(raw, agent_id=AGENT_ID) for raw in raw_tokens)
        overall_confidence = require_float(parsed, "overall_confidence", agent_id=AGENT_ID, default=0.0)

        for token in tokens:
            if (
                _looks_consequential(token.text)
                and token.asr_confidence is not None
                and token.asr_confidence < _CONSEQUENTIAL_CONFIDENCE_FLOOR
            ):
                raise ConsequentialSpanUnclear(
                    turn_id=turn_id, span_text=token.text, confidence=token.asr_confidence
                )

        return TranscriptionResult(
            turn_id=turn_id,
            raw_text=raw_text,
            tokens=tokens,
            overall_confidence=overall_confidence,
            model_tier="flash",
            invocation_id=uuid.uuid4().hex,
            transcribed_at=datetime.now(UTC),
        )


__all__ = ["AGENT_ID", "SpeechRecognitionHandler"]
