"""A64 — Language & Script Identifier (spec §14.2, §14.4, §15.11,
PHASES.md Phase 13, ADR-020 Decision 2) — E2's
`backend/app/agents/voice/`.

*Responsibility:* per-**span** (never per-utterance) language tagging over
one voice turn's real transcript. Real Indian household speech is
intra-sentential code-mixed (spec §14.2: *"Aarav ko Friday ko field trip
hai, permission slip sign karna hai"*) — treating "detect language, then
translate" as a whole-utterance operation "fails badly" (spec's own
words), so this agent's prompt asks for, and this module's parsing
enforces, span-level output only.

**Hindi/Marathi disambiguation is lexical and grammatical, never
script-based** (spec §14.2: both languages share Devanagari; script
detection cannot tell them apart). The prompt this module loads
(`backend/app/prompts/a64_language_script_identifier/v1.md`) spells out
concrete lexical/grammatical markers (distinct copulas, possessive
suffixes, negation forms) the model must use — never "which script is
this written in."

**Ambiguity handling (spec §15.11 A64 failure mode): "ambiguous short
utterance -> fall back to speaker's `primary_language`, flag low
confidence."** Implemented here, in code, not left to the model: any span
whose model-reported confidence falls below `_AMBIGUITY_CONFIDENCE_FLOOR`,
or that the model itself reports as lexically ambiguous between two or
more languages (`ambiguous_between` non-empty), has its `language`
field overridden to `SpeakerLanguageContext.language_profile.
primary_language` when a speaker profile is available, and is always
marked `fallback_applied` accordingly — a caller (or a test) can always
tell a genuinely confident tag from a rescued one. When no speaker
profile is available at all (the caller reports a genuinely unidentified
speaker — A66's own, separate failure mode, not this agent's job to
resolve), the model's own best-guess language is kept, unchanged, but
still reported as ambiguous via `ambiguous_between`.

*Model tier:* Flash only (spec §15.11 A64) — this agent is **not** on
`model_router.PRO_TIER_ALLOWLIST` and must never request `ModelTier.PRO`.

*Forbidden:* resolving *who* is speaking (A66, E3's job — this module
holds no speaker-identification logic and no `GraphReader`); "cleaning
up" `raw_text` into fluent monolingual text (A63's forbidden list, which
this agent's own prompt is written to respect on the read side: it tags
`raw_text` as given, verbatim, never rewrites it). Holds no tool of any
kind, no import of `app.arbitration` — see
`backend/tests/test_voice_agents_arbitration_boundary.py`.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_float, require_int, require_list, require_str
from .types import (
    SUPPORTED_LANGUAGES,
    LanguageIdentificationRequest,
    LanguageIdentificationResult,
    LanguageSpan,
)

AGENT_ID = AgentId("A64")

_AMBIGUITY_CONFIDENCE_FLOOR = 0.6
"""Below this, a span's model-reported language tag is not trusted on its
own — a fallback to the speaker's `primary_language` is attempted (spec
§15.11 A64 failure mode). Deliberately more permissive than
`_HARD_CONSTRAINT_CONFIDENCE_FLOOR`-style floors elsewhere in this
codebase (e.g. `constraint_checker.py`'s 0.75) — language tagging is not
itself a safety-critical judgment the way a hard-constraint violation is;
what *is* safety-critical is that downstream amount/name confirmation
(A65/A68) never silently inherits an unflagged low-confidence tag, which
`fallback_applied`/`ambiguous_between` guarantee it does not."""


def _parse_span(raw: object, *, agent_id: AgentId) -> LanguageSpan:
    if not isinstance(raw, dict):
        raise ModelResponseMalformed(
            agent_id=agent_id, reason=f"expected a span object, got {type(raw).__name__}", raw_text=str(raw)
        )
    text = require_str(raw, "text", agent_id=agent_id)
    start_char = require_int(raw, "start_char", agent_id=agent_id)
    end_char = require_int(raw, "end_char", agent_id=agent_id)
    language = require_str(raw, "language", agent_id=agent_id)
    if language not in SUPPORTED_LANGUAGES:
        raise ModelResponseMalformed(
            agent_id=agent_id,
            reason=f"language {language!r} is not one of {sorted(SUPPORTED_LANGUAGES)} (spec §14.2)",
            raw_text=str(raw),
        )
    confidence = require_float(raw, "confidence", agent_id=agent_id)
    ambiguous_raw = raw.get("ambiguous_between", [])
    if ambiguous_raw is None:
        ambiguous_raw = []
    if not isinstance(ambiguous_raw, list):
        raise ModelResponseMalformed(
            agent_id=agent_id,
            reason=f"expected array field 'ambiguous_between', got {type(ambiguous_raw).__name__}",
            raw_text=str(raw),
        )
    ambiguous_between = tuple(item for item in ambiguous_raw if isinstance(item, str))

    return LanguageSpan(
        text=text,
        start_char=start_char,
        end_char=end_char,
        language=language,
        confidence=confidence,
        fallback_applied=False,
        ambiguous_between=ambiguous_between,
    )


def _apply_fallback(span: LanguageSpan, *, primary_language: str | None) -> LanguageSpan:
    """Applies spec §15.11 A64's failure-mode rule to one span. Never
    mutates in place (every dataclass in this package is frozen) —
    returns either the original span unchanged, or a fallback-applied
    replacement."""
    is_ambiguous = span.confidence < _AMBIGUITY_CONFIDENCE_FLOOR or len(span.ambiguous_between) > 1

    if not is_ambiguous:
        return span

    if primary_language is None:
        # No speaker profile to fall back to (A66's own separate "unknown
        # speaker" path) — keep the model's best guess, but the caller
        # still sees `ambiguous_between` non-empty when the model reported
        # a real lexical ambiguity.
        return span

    return replace(span, language=primary_language, fallback_applied=True)


class LanguageScriptIdentifierAgent:
    """A64 Language & Script Identifier. Dependency-injected on a
    `GeminiClient` only — no `GraphReader`, no tool of any kind."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def identify(self, request: LanguageIdentificationRequest) -> LanguageIdentificationResult:
        """Tags `request.raw_text` with real, per-span language labels.

        Args:
            request: the real turn transcript plus the caller-resolved
                speaker language context.

        Returns:
            A `LanguageIdentificationResult` whose `spans` collectively
            cover `request.raw_text`.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape.
        """
        prompt = load_prompt("A64")
        rendered = prompt.text.format(raw_text=request.raw_text)
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_spans = require_list(parsed, "spans", agent_id=AGENT_ID)
        if not raw_spans:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="response contained no spans", raw_text=call_result.text
            )

        primary_language = (
            request.speaker.language_profile.primary_language
            if request.speaker.language_profile is not None
            else None
        )

        spans = tuple(
            _apply_fallback(_parse_span(raw, agent_id=AGENT_ID), primary_language=primary_language)
            for raw in raw_spans
        )
        overall_confidence = require_float(parsed, "overall_confidence", agent_id=AGENT_ID)

        return LanguageIdentificationResult(
            turn_id=request.turn_id,
            spans=spans,
            overall_confidence=overall_confidence,
            model_tier="flash",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            identified_at=datetime.now(UTC),
        )


__all__ = ["AGENT_ID", "LanguageScriptIdentifierAgent"]
