"""A65 — Normalisation Agent (spec §14.2, §14.3, §14.6, §15.11,
PHASES.md Phase 13, ADR-020 Decision 4) — E2's
`backend/app/agents/voice/`.

*Responsibility:* transliteration variance ("nahi"/"nahin"/"nhi" -> one
canonical spelling), numerals (lakh/crore, spoken amounts like "saade
teen hazaar" -> `3500` + `"₹3,500"`), dates, and kinship-term span
tagging, over A64's real per-span-tagged transcript. **Never resolves a
kinship term to a `Person` id** — that is A5 Entity Resolution's job
(Phase 3, downstream); this agent only marks a span `kind="kinship"` so
it becomes a candidate for A5, and normalises its *transliteration*
(e.g. consistent romanisation of the same word), never its *meaning*
(different kinship words for the same role — "Amma"/"Aai"/"Maa" — are
never collapsed into one, because they are not spelling variants of the
same word; only genuine respellings of the identical word are).

**Never discards the original text — unconditionally.** Every
`types.NormalizedSpan` this agent produces carries `original_text`
alongside `normalized_text`, for every span, including spans requiring no
change at all (spec §15.11 A65 forbidden list).

**Amount disambiguation, exactly per ADR-020 Decision 4 and spec §15.11 A65
failure mode ("always clarify, never round or guess"):**

1. A Flash-tier pass normalises the whole turn (transliteration, dates,
   kinship tagging, and every amount span it can confidently resolve on
   its own).
2. Any amount span the Flash pass itself flags `ambiguous: true` is
   escalated — **in a single batched Pro-tier call, never per-span** (cost
   discipline) — for a genuine second attempt at disambiguation.
3. An amount still ambiguous after that Pro-tier attempt is never resolved
   by picking a number (an average, the first candidate, anything) — it is
   returned with `needs_clarification=True`, `amount_value=None`,
   `amount_display=None`, and a real `clarification_reason` (e.g. "spoken
   as an approximate range, not a single figure" — the realistic Hindi
   household idiom "teen-chaar hazaar", "three-four thousand", is
   genuinely a range, not a mistranscription, and this module's own test
   suite covers exactly this case).

The digit-grouped display string (`NormalizedSpan.amount_display`) is
**always** produced by `formatting.format_inr` — deterministic code, never
model output — once a numeric value is resolved, at either tier.

*Model tier:* Flash by default; Pro-tier **only** for the batched amount
disambiguation call (`model_router.PRO_TIER_ALLOWLIST` entry "A65 —
ambiguous-amount disambiguation only").

*Forbidden:* discarding the original text (structurally impossible here —
see above); guessing/rounding an ambiguous amount (structurally
impossible — `needs_clarification` spans never carry a numeric value at
all, checked directly in `backend/tests/test_normalisation_agent.py`).
Holds no tool, no `GraphReader`, no import of `app.arbitration`.
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
from .formatting import format_inr
from .json_utils import (
    optional_str,
    parse_json_response,
    require_bool,
    require_float,
    require_int,
    require_list,
    require_str,
)
from .types import NormalizationRequest, NormalizationResult, NormalizedSpan, SpanKind

AGENT_ID = AgentId("A65")

_VALID_KINDS: frozenset[str] = frozenset({"plain", "amount", "date", "kinship"})


def _parse_flash_span(raw: object, *, agent_id: AgentId) -> tuple[NormalizedSpan, bool]:
    """Parses one span from the Flash-tier pass.

    Returns:
        The parsed `NormalizedSpan` (amount fields unset when this span
        is flagged ambiguous — filled in later, either from this same
        span's own resolved fields or by the Pro-tier escalation pass)
        plus whether the Flash pass itself flagged this amount span as
        ambiguous and needing escalation.
    """
    if not isinstance(raw, dict):
        raise ModelResponseMalformed(
            agent_id=agent_id, reason=f"expected a span object, got {type(raw).__name__}", raw_text=str(raw)
        )
    original_text = require_str(raw, "original_text", agent_id=agent_id)
    normalized_text = require_str(raw, "normalized_text", agent_id=agent_id)
    kind_raw = require_str(raw, "kind", agent_id=agent_id)
    if kind_raw not in _VALID_KINDS:
        raise ModelResponseMalformed(
            agent_id=agent_id, reason=f"kind {kind_raw!r} not one of {_VALID_KINDS}", raw_text=str(raw)
        )
    kind: SpanKind = kind_raw  # type: ignore[assignment]
    language = require_str(raw, "language", agent_id=agent_id)
    start_char = require_int(raw, "start_char", agent_id=agent_id)
    end_char = require_int(raw, "end_char", agent_id=agent_id)

    is_ambiguous_amount = False
    amount_value: float | None = None
    amount_display: str | None = None
    if kind == "amount":
        is_ambiguous_amount = require_bool(raw, "ambiguous", agent_id=agent_id, default=False)
        if not is_ambiguous_amount:
            amount_value = require_float(raw, "amount_value", agent_id=agent_id)
            amount_display = format_inr(amount_value)

    return (
        NormalizedSpan(
            original_text=original_text,
            normalized_text=normalized_text,
            kind=kind,
            language=language,
            start_char=start_char,
            end_char=end_char,
            amount_value=amount_value,
            amount_display=amount_display,
            needs_clarification=False,
            clarification_reason=None,
        ),
        is_ambiguous_amount,
    )


def _parse_amount_resolution(raw: object, *, agent_id: AgentId) -> tuple[str, float | None, str | None]:
    """Parses one entry of the Pro-tier disambiguation pass's
    `resolutions` array.

    Returns:
        `(original_text, resolved_value_or_none, clarification_reason_or_none)`.
    """
    if not isinstance(raw, dict):
        raise ModelResponseMalformed(
            agent_id=agent_id,
            reason=f"expected a resolution object, got {type(raw).__name__}",
            raw_text=str(raw),
        )
    original_text = require_str(raw, "original_text", agent_id=agent_id)
    resolved = require_bool(raw, "resolved", agent_id=agent_id)
    if resolved:
        return original_text, require_float(raw, "amount_value", agent_id=agent_id), None
    reason = optional_str(raw, "clarification_reason") or "amount remained ambiguous after disambiguation"
    return original_text, None, reason


class NormalisationAgent:
    """A65 Normalisation Agent. Dependency-injected on a `GeminiClient`
    only — no `GraphReader`, no tool of any kind."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def normalize(self, request: NormalizationRequest) -> NormalizationResult:
        """Normalises `request`'s per-span-tagged transcript.

        Args:
            request: A64's real language spans plus the household's
                reference date.

        Returns:
            A `NormalizationResult`. See module docstring for the amount
            disambiguation policy.

        Raises:
            errors.ModelResponseMalformed: a model response could not be
                parsed as the expected JSON shape.
        """
        spans_block = "\n".join(
            f'- "{span.text}" (chars {span.start_char}-{span.end_char}, language={span.language})'
            for span in request.language_spans
        )
        prompt = load_prompt("A65")
        rendered = prompt.text.format(
            raw_text=request.raw_text, spans_block=spans_block, reference_date=request.reference_date
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_spans = require_list(parsed, "spans", agent_id=AGENT_ID)

        parsed_spans: list[NormalizedSpan] = []
        ambiguous_originals: list[str] = []
        for raw_span in raw_spans:
            span, is_ambiguous = _parse_flash_span(raw_span, agent_id=AGENT_ID)
            parsed_spans.append(span)
            if is_ambiguous:
                ambiguous_originals.append(span.original_text)

        escalated_to_pro = False
        if ambiguous_originals:
            escalated_to_pro = True
            ambiguous_block = "\n".join(f'- "{text}"' for text in ambiguous_originals)
            amount_prompt = load_prompt("A65_AMOUNT")
            amount_rendered = amount_prompt.text.format(
                raw_text=request.raw_text, ambiguous_block=ambiguous_block
            )
            amount_call_result = self._gemini_client.generate_structured(
                agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=amount_rendered
            )
            amount_parsed = parse_json_response(agent_id=AGENT_ID, text=amount_call_result.text)
            raw_resolutions = require_list(amount_parsed, "resolutions", agent_id=AGENT_ID)
            resolutions = {
                original_text: (value, reason)
                for original_text, value, reason in (
                    _parse_amount_resolution(raw, agent_id=AGENT_ID) for raw in raw_resolutions
                )
            }

            resolved_spans: list[NormalizedSpan] = []
            for span in parsed_spans:
                if span.kind != "amount" or span.original_text not in resolutions:
                    resolved_spans.append(span)
                    continue
                value, reason = resolutions[span.original_text]
                if value is not None:
                    resolved_spans.append(replace(span, amount_value=value, amount_display=format_inr(value)))
                else:
                    resolved_spans.append(
                        replace(span, needs_clarification=True, clarification_reason=reason)
                    )
            parsed_spans = resolved_spans

        any_needs_clarification = any(span.needs_clarification for span in parsed_spans)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        return NormalizationResult(
            turn_id=request.turn_id,
            spans=tuple(parsed_spans),
            any_needs_clarification=any_needs_clarification,
            confidence=confidence,
            model_tier="pro" if escalated_to_pro else "flash",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            normalized_at=datetime.now(UTC),
        )


__all__ = ["AGENT_ID", "NormalisationAgent"]
