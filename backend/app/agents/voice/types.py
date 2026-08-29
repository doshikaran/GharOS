"""Shared, non-agent-specific dataclasses for the inbound voice reasoning
agents (A64, A65, A67, A68 — spec §14, §15.11, PHASES.md Phase 13,
ADR-020) — E2's `backend/app/agents/voice/`.

Mirrors the role `app.agents.council.types` / `app.agents.concierge.types`
already play for their own packages: one place every module in this
package imports the same request/result shapes from, so the pipeline
(language-tag -> normalise -> classify intent -> [confirm]) stays legible
end to end, and so E3's orchestrator (`backend/app/voice/session_
manager.py`, next wave) has one file to read to see exactly what it hands
to, and gets back from, each of E2's four agents.

**Pre-resolved-by-the-caller discipline, per this codebase's established
precedent** (`app.agents.concierge.types.ClarificationRequest.known_facts`,
`app.agents.ledger.types.PayrollRequest`, `app.agents.council.types.
SpecialistReportRequest`): none of A64/A65/A67/A68 hold a `GraphReader`.
Speaker identity (A66, E3) and any graph fact a request needs (a person's
`LanguageProfile`, a name's household relationship label) are resolved by
the caller and passed in as plain data on the request types below —
consistent with every other Flash/Pro-tier reasoning agent in this
codebase that needs a graph fact it does not hold read access to itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal

from contracts.actions import RiskTier
from contracts.graph_types import LanguageProfile, NodeId

# ---------------------------------------------------------------------------
# Cross-agent primitives
# ---------------------------------------------------------------------------

SupportedLanguage = Literal["en", "hi", "mr", "es"]
"""Spec §14.2's fixed four-language set. Never extended without a CTO/ADR
decision (ADR-020 Decision 2 froze this set for the phase)."""

SUPPORTED_LANGUAGES: frozenset[str] = frozenset({"en", "hi", "mr", "es"})


@dataclass(frozen=True, slots=True)
class TranscriptToken:
    """One token of A63's real streaming-ASR output (E3,
    `backend/app/voice/`) — the input shape this package's A64 consumes.
    `asr_confidence` is A63's own per-token, model-self-reported
    confidence (ADR-020 Decision 1: Vertex AI's `generateContent` audio
    path exposes no true acoustic logprobs; A63's own module docstring
    discloses this) — `None` only when A63 could not produce a per-token
    figure for this token at all."""

    text: str
    start_ms: int | None
    end_ms: int | None
    asr_confidence: float | None


@dataclass(frozen=True, slots=True)
class SpeakerLanguageContext:
    """The caller-resolved (via A66 Speaker Identification, E3) speaker
    identity + language profile for one turn. `person_id` is `None` only
    for A66's own genuine "unknown speaker" failure path (spec §15.11
    A66: "restrict to R0/R1 actions only") — this package's agents never
    resolve speaker identity themselves; they only ever consume what the
    caller already determined."""

    person_id: NodeId | None
    language_profile: LanguageProfile | None
    """`None` exactly when `person_id` is `None` — an unidentified speaker
    has no resolvable language profile either."""


# ---------------------------------------------------------------------------
# A64 — Language & Script Identifier
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LanguageIdentificationRequest:
    """A64's input for one voice turn."""

    turn_id: str
    raw_text: str
    """The full turn transcript, exactly as A63 produced it — code-mixed,
    never "cleaned up" (spec §15.2 A63's own forbidden list, which this
    package's every prompt is written to respect on the read side too:
    never asking the model to translate or monolingualise `raw_text`)."""
    tokens: tuple[TranscriptToken, ...]
    speaker: SpeakerLanguageContext


@dataclass(frozen=True, slots=True)
class LanguageSpan:
    """One per-span language tag (spec §15.11 A64: "per-span, not
    per-utterance"). `start_char`/`end_char` index into the *same*
    `LanguageIdentificationRequest.raw_text` string this span was cut
    from — never a re-normalised copy, so a caller can always recover the
    exact original substring."""

    text: str
    start_char: int
    end_char: int
    language: str
    """One of `SUPPORTED_LANGUAGES`."""
    confidence: float
    fallback_applied: bool
    """`True` only when the model's own confidence for this span fell
    below `language_script_identifier_agent._AMBIGUITY_CONFIDENCE_FLOOR`
    (or the model itself reported more than one candidate language) and a
    fallback to `SpeakerLanguageContext.language_profile.primary_language`
    was applied (spec §15.11 A64 failure mode). `False` for every
    confidently-tagged span, including ones the model itself never
    considered ambiguous."""
    ambiguous_between: tuple[str, ...]
    """Non-empty only when the model reported genuine lexical/grammatical
    ambiguity between two or more languages for this span (the
    Hindi/Marathi shared-Devanagari case spec §14.2 names explicitly) —
    populated regardless of whether a fallback was possible, so a caller
    can see *what* was ambiguous even when `fallback_applied` is `False`
    (no speaker language profile was available to fall back to)."""


@dataclass(frozen=True, slots=True)
class LanguageIdentificationResult:
    """A64's entire output for one turn."""

    turn_id: str
    spans: tuple[LanguageSpan, ...]
    overall_confidence: float
    model_tier: Literal["flash"]
    prompt_version: str
    invocation_id: str
    identified_at: datetime


# ---------------------------------------------------------------------------
# A65 — Normalisation Agent
# ---------------------------------------------------------------------------

SpanKind = Literal["plain", "amount", "date", "kinship"]


@dataclass(frozen=True, slots=True)
class NormalizationRequest:
    """A65's input for one turn — A64's real per-span output, never
    re-derived here."""

    turn_id: str
    raw_text: str
    language_spans: tuple[LanguageSpan, ...]
    reference_date: str
    """ISO `YYYY-MM-DD` — "today" from the household's own clock, needed
    to resolve a relative date expression ("kal", "Friday") to an
    absolute one. Caller-supplied (this package holds no clock access of
    its own, consistent with its no-I/O-dependency design)."""


@dataclass(frozen=True, slots=True)
class NormalizedSpan:
    """One normalised span. `original_text` is carried unconditionally on
    every single instance — spec §15.11 A65's own forbidden list:
    "discarding the original text" — never optional, never `None`, never
    dropped for a span that needed no normalisation at all (in that case
    `normalized_text == original_text`)."""

    original_text: str
    normalized_text: str
    kind: SpanKind
    language: str
    start_char: int
    end_char: int
    amount_value: float | None = None
    """Resolved numeric rupee value, set only for `kind == "amount"` spans
    that were confidently resolved (Flash alone, or Flash escalated to
    Pro-tier and resolved there). `None` for a genuinely ambiguous amount
    — see `needs_clarification`."""
    amount_display: str | None = None
    """`app.agents.voice.formatting.format_inr(amount_value)` — always
    set together with `amount_value`, always `None` when it is."""
    needs_clarification: bool = False
    """`True` only for `kind == "amount"` spans that remained ambiguous
    even after Pro-tier escalation (spec §15.11 A65 failure mode: "always
    clarify, never round or guess"). When `True`, `amount_value` and
    `amount_display` are both `None` — there is no fallback numeric
    guess."""
    clarification_reason: str | None = None
    """Set only when `needs_clarification` is `True` — a short, real
    explanation (e.g. "spoken as an approximate range, not a single
    figure") a caller can surface back to the household when asking the
    clarifying question."""


@dataclass(frozen=True, slots=True)
class NormalizationResult:
    """A65's entire output for one turn."""

    turn_id: str
    spans: tuple[NormalizedSpan, ...]
    any_needs_clarification: bool
    confidence: float
    model_tier: Literal["flash", "pro"]
    """`"pro"` only when at least one amount span was escalated for
    disambiguation this run (ADR-020 Decision 4: "ambiguous-amount
    escalation only") — `"flash"` for every turn with no ambiguous
    amount, which is the common case."""
    prompt_version: str
    invocation_id: str
    normalized_at: datetime


# ---------------------------------------------------------------------------
# A67 — Voice Intent Classifier
# ---------------------------------------------------------------------------


class VoiceIntentClass(StrEnum):
    """Spec §14.5's exact seven-class table — closed set, never extended
    without a spec/ADR change."""

    CAPTURE = "capture"
    INTENTION = "intention"
    COMMAND = "command"
    QUERY = "query"
    APPROVAL = "approval"
    DECISION_TRIGGER = "decision_trigger"
    CORRECTION = "correction"


@dataclass(frozen=True, slots=True)
class VoiceIntentRequest:
    """A67's input for one turn — A65's real normalised spans, never
    re-normalised here."""

    turn_id: str
    raw_text: str
    normalized_spans: tuple[NormalizedSpan, ...]
    speaker: SpeakerLanguageContext
    prior_turn_summary: str | None = None
    """Plain-language gist of the immediately preceding turn, when one
    exists — the only context a `CORRECTION` ("no, that's Kaku not Baba")
    can be classified against at all. Caller-supplied (session history is
    A62's, E3's, to track); `None` for a turn opening a fresh session."""


@dataclass(frozen=True, slots=True)
class VoiceIntentResult:
    """A67's entire output for one turn. `risk_tier` is populated only
    for the three intent classes spec §14.5 actually names a tier for
    (`COMMAND` -> R0/R1, `APPROVAL` -> R2/R3, `DECISION_TRIGGER` -> always
    `R4_ESCALATE_ONLY`, structurally, never taken from the model — see
    `voice_intent_classifier_agent.py`) — `None` for `CAPTURE`/
    `INTENTION`/`QUERY`/`CORRECTION`, whose eventual risk tier (if any) is
    decided downstream by the subsystem they route to, not by this
    classifier."""

    turn_id: str
    intent: VoiceIntentClass
    risk_tier: RiskTier | None
    target_summary: str
    requires_confirmation: bool
    """`True` exactly when spec §14.6's mandatory-read-back rule applies
    to this turn — computed deterministically in code
    (`voice_intent_classifier_agent._requires_confirmation`), never left
    to the model's own discretion alone."""
    reasoning: str
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str
    classified_at: datetime


# ---------------------------------------------------------------------------
# A68 — Confirmation Agent
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NameReference:
    """One person's name-plus-relationship for a read-back needing
    disambiguation (spec §14.6 rule 3: "names are read with their graph
    relationship" — e.g. "Aarav, your son"). `relationship_to_speaker` is
    pre-resolved by the caller from the graph (this package holds no
    `GraphReader`, per the module docstring's discipline)."""

    display_name: str
    relationship_to_speaker: str


@dataclass(frozen=True, slots=True)
class ReadbackRequest:
    """A68's input for generating one read-back prompt."""

    turn_id: str
    intent: VoiceIntentResult
    amount_spans: tuple[NormalizedSpan, ...]
    """Every `kind == "amount"` span relevant to what is being confirmed
    — each must already have a non-`None` `amount_display` (an amount
    still needing clarification, per A65, is never sent to A68 for a
    read-back at all; the caller asks the clarifying question first)."""
    name_references: tuple[NameReference, ...]
    date_spans: tuple[NormalizedSpan, ...]
    speaker_language: str


@dataclass(frozen=True, slots=True)
class ReadbackResult:
    """A68's real, spoken-ready read-back text plus tracing metadata."""

    turn_id: str
    readback_text: str
    requires_affirmative: bool
    """Mirrors ADR-020's WebSocket `confirmation_prompt` message shape
    field of the same name — always `True` for a `ReadbackResult` this
    agent produces (spec §14.6's read-back path is only ever entered when
    confirmation is actually required); kept as an explicit field rather
    than an implicit constant so a caller serialising this straight onto
    the wire message never has to remember to set it separately."""
    confidence: float
    model_tier: Literal["pro"]
    prompt_version: str
    invocation_id: str
    generated_at: datetime


@dataclass(frozen=True, slots=True)
class ConfirmationEvaluationRequest:
    """A68's input for evaluating the household member's real spoken
    response to a prior read-back."""

    turn_id: str
    readback_text: str
    spoken_response_text: str | None
    """`None` or an empty/whitespace-only string both represent silence —
    `affirmatives.check_affirmative` treats them identically (spec §14.6
    rule 4)."""
    speaker_language: str


@dataclass(frozen=True, slots=True)
class ConfirmationResult:
    """A68's entire output for one confirmation turn. Deliberately holds
    **no** `risk_tier`, `authorized`, or any other field that could let a
    caller treat this result itself as an authorisation to act — see this
    module's own test coverage
    (`backend/tests/test_confirmation_agent.py::
    TestStructuralNeverAnAuthorisation`) for the direct proof. Whether an
    R3 request may proceed off the back of `confirmed=True` is a decision
    for the Approval Gate / voice orchestrator (E3, next wave) to make
    with its own knowledge of the action's risk tier — never this type's
    concern (ADR-020 Decision 5, item 3: "R3 is never approved by voice
    alone... resolved only through the existing visual approval queue")."""

    turn_id: str
    confirmed: bool
    reason: str
    matched_affirmative_phrase: str | None
    """The exact canonical phrase `affirmatives.check_affirmative` matched
    (before any Pro-tier semantic narrowing), or `None` when nothing
    matched at all (silence, or a genuinely non-affirmative reply)."""
    model_tier: Literal["pro", "deterministic"]
    """`"deterministic"` when the structural affirmative-table check alone
    already resolved to `confirmed=False` (silence or no match — no
    Gemini call is made at all, mirroring `app.agents.concierge.
    confirmation_verifier_agent`'s identical "nothing to narrate"
    discipline). `"pro"` only when a canonical phrase matched and the
    semantic narrowing call actually ran."""
    prompt_version: str
    invocation_id: str
    evaluated_at: datetime


__all__ = [
    "SUPPORTED_LANGUAGES",
    "ConfirmationEvaluationRequest",
    "ConfirmationResult",
    "LanguageIdentificationRequest",
    "LanguageIdentificationResult",
    "LanguageSpan",
    "NameReference",
    "NormalizationRequest",
    "NormalizationResult",
    "NormalizedSpan",
    "ReadbackRequest",
    "ReadbackResult",
    "SpanKind",
    "SpeakerLanguageContext",
    "SupportedLanguage",
    "TranscriptToken",
    "VoiceIntentClass",
    "VoiceIntentRequest",
    "VoiceIntentResult",
]
