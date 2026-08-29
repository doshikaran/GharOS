"""Shared, non-agent-specific dataclasses/enums for E3's
`backend/app/voice/` (A62 Voice Session Manager, A63 Speech Recognition
Handler, A66 Speaker Identification, A69 Voice Response Agent — spec §14,
§15.11, PHASES.md Phase 13, ADR-020).

Mirrors the role `app.agents.voice.types` plays for E2's four reasoning
agents: one place every module in this package imports the same
request/result shapes from. `app.agents.voice.types.TranscriptToken` is
reused directly (not redefined) — it is A63's own real output shape and
A64's own real input shape; duplicating it here would let the two drift.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal

from contracts.graph_types import NodeId

from app.agents.voice.types import TranscriptToken

# ---------------------------------------------------------------------------
# A62 — Voice Session Manager
# ---------------------------------------------------------------------------


class SessionState(StrEnum):
    """ADR-020 Decision 3's WebSocket `session_state` values, exactly —
    the wire contract's own vocabulary, not an independently-invented
    one."""

    LISTENING = "listening"
    PROCESSING = "processing"
    SPEAKING = "speaking"
    CLOSED = "closed"


# ---------------------------------------------------------------------------
# A63 — Speech Recognition Handler
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class TranscriptionResult:
    """A63's entire output for one turn's raw audio.

    `tokens[i].asr_confidence` is a MODEL-SELF-REPORTED, per-segment
    confidence, never true acoustic confidence — see
    `speech_recognition_handler.py`'s module docstring (ADR-020
    Decision 1) for the full disclosure."""

    turn_id: str
    raw_text: str
    tokens: tuple[TranscriptToken, ...]
    overall_confidence: float
    model_tier: Literal["flash"]
    invocation_id: str
    transcribed_at: datetime


# ---------------------------------------------------------------------------
# A66 — Speaker Identification
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrolledSpeaker:
    """One household member's enrolled reference clip, resolved by the
    caller (the session manager, or the enrollment endpoint's own
    verification step) from `contracts.graph_types.Person.voiceprint_ref`
    via `app.persistence.raw_payload_store.RawPayloadStore` — this
    package holds no store of its own, mirroring `app.agents.voice`'s
    "the caller resolves graph/storage facts, the agent only judges"
    discipline."""

    person_id: NodeId
    display_name: str
    reference_audio: bytes
    reference_mime_type: str


@dataclass(frozen=True, slots=True)
class SpeakerIdentificationResult:
    """A66's entire output for one turn.

    `person_id` is `None` exactly when no enrolled speaker cleared
    `speaker_identification._SPEAKER_MATCH_CONFIDENCE_FLOOR` — spec
    §15.11 A66's own failure mode: "unknown speaker -> restrict to R0/R1
    actions only." `matched_against_person_ids` is non-empty even on an
    unknown-speaker result, proving real comparisons were attempted
    (never skipped, never guessed)."""

    person_id: NodeId | None
    display_name: str | None
    confidence: float
    matched_against_person_ids: tuple[NodeId, ...]
    invocation_id: str
    identified_at: datetime


# ---------------------------------------------------------------------------
# A69 — Voice Response Agent
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PacingProfile:
    """A real, if simple, pacing policy — computed deterministically in
    `pacing.py` from a `contracts.graph_types.LanguageProfile` plus an
    elder/noisy-environment signal, never left to the model's own
    discretion. `style_instruction` is prepended, verbatim, to the text
    handed to the TTS model — the real, live-verified mechanism for
    controlling a Gemini TTS call's delivery (the `google.genai`
    `types.SpeechConfig` shape this project's SDK version exposes has no
    dedicated rate/SSML parameter at all — confirmed by direct
    introspection this phase, not assumed; natural-language style
    instruction is the only real control surface available)."""

    style_instruction: str
    language_code: str
    """A BCP-47 tag (e.g. `"hi-IN"`) passed as `SpeechConfig.language_code`
    — an explicit hint rather than relying on the TTS model's own
    auto-detection from `SupportedLanguage`."""


@dataclass(frozen=True, slots=True)
class ResponseRequest:
    """A69's input for one spoken response.

    `content_summary` is the plain-language gist of what to say —
    supplied by the caller (whichever subsystem has the real facts: a
    query answer, a read-back prompt, an acknowledgement). A69 phrases
    and paces it; it never invents a fact of its own (mirrors
    `app.agents.concierge.call_planner_agent`/`confirmation_verifier_
    agent`'s established "never generates facts it wasn't given"
    discipline)."""

    turn_id: str
    speaker_language: str
    content_summary: str
    response_kind: Literal[
        "acknowledgement", "answer", "confirmation_prompt", "clarification_request", "error", "farewell"
    ]
    pacing: PacingProfile
    list_items: tuple[str, ...] = field(default_factory=tuple)
    """Populated only when `content_summary` narrates a list — spec's own
    A69 forbidden list: "reading long lists aloud or narrating the
    graph." Enforced structurally, not just by prompt instruction — see
    `voice_response_agent._cap_item_enumeration`: at 3 or more items, the
    model is shown (and can therefore only speak) a capped prefix plus a
    deferral instruction, never the full list."""
    voice_name: str = "Kore"
    """A live-verified prebuilt Gemini TTS voice (this phase's own
    verification call) that renders intelligibly across all four
    supported languages without a per-language voice switch — see
    `voice_response_agent.py`'s module docstring for the verification
    detail."""


@dataclass(frozen=True, slots=True)
class VoiceResponseResult:
    """A69's entire output for one turn."""

    turn_id: str
    spoken_text: str
    audio_bytes: bytes
    audio_mime_type: str
    """The real MIME type Vertex AI returned (this phase's live
    verification: `"audio/L16;codec=pcm;rate=24000"` — raw 24kHz PCM16,
    not a compressed container) — reported honestly, never coerced to a
    different label the caller might expect."""
    language: str
    deferred_full_list: bool
    confidence: float
    model_tier: Literal["pro"]
    invocation_id: str
    produced_at: datetime


# ---------------------------------------------------------------------------
# Enrollment / language-profile tool shapes (item 5 — mic/telephony wiring)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EnrollmentResult:
    """`enrollment_tool.VoiceprintEnrollmentTool`'s real output."""

    person_id: NodeId
    voiceprint_ref: str
    enrolled_at: datetime


__all__ = [
    "EnrolledSpeaker",
    "EnrollmentResult",
    "PacingProfile",
    "ResponseRequest",
    "SessionState",
    "SpeakerIdentificationResult",
    "TranscriptionResult",
    "VoiceResponseResult",
]
