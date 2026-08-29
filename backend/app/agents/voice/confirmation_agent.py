"""A68 — Confirmation Agent (spec §14.6, §15.11, PHASES.md Phase 13,
ADR-020) — E2's `backend/app/agents/voice/`.

*Responsibility:* enforce spec §14.6's read-back discipline — the safety
core of voice. Two operations, deliberately asymmetric in how much they
trust a model call, mirroring `app.agents.concierge.
confirmation_verifier_agent`'s established structural-first, semantic-
second design:

**1. `generate_readback` — Pro-tier, structurally checked afterwards.**
Produces `readback_text` in the speaker's own language using the
*normalised, unambiguous* form (never the raw ambiguous phrase — spec
§14.6 rule 1: echoing "saade teen hazaar" back would confirm nothing).
After the model call, this module verifies **by substring check, not by
trusting the prompt**, that every real amount's digit-grouped display
string (`formatting.format_inr`, deterministic) and every real name's
`NameReference.display_name` + `relationship_to_speaker` actually appear
in the produced text — raising `errors.ModelResponseMalformed` if any
required fact is missing from what the model actually said. The "in
words, repeated" phrasing (spec §14.6 rule 2: "₹3,500 — three thousand
five hundred") is left to the model's own language generation — the
*number itself* is what is structurally guaranteed correct, never the
prose around it.

**2. `evaluate_response` — deterministic first, Pro-tier only to narrow,
never to widen.** Spec §14.6 rule 4 and this agent's own forbidden list:
"treating silence or ambiguity as approval" must never happen, **even if
the LLM call fails or returns something unexpected** (this phase's own
dispatch instructions). So:

  a. `affirmatives.check_affirmative` — a real, enumerated, per-language
     phrase table, **zero model calls** — is checked first. Silence
     (`None` or blank) or a response matching nothing in the table
     resolves to `confirmed=False` immediately, `model_tier=
     "deterministic"`. This is the *entire* proof of the hard rule: no
     code path exists from "nothing matched" to `confirmed=True"` that
     passes through a model call at all.
  b. Only when a canonical phrase *did* match does a Pro-tier semantic
     check run at all — to catch a real edge case a bare keyword match
     would miss: a matched affirmative token used inside a negating or
     hedging clause ("haan, lekin abhi nahi" — "yes, but not right now").
     This call can only turn a structural match into `confirmed=False`
     (narrowing), **never** the reverse — there is no code path in this
     module that reads a `"confirmed": true` key out of parsed model
     JSON at all (mirrors `confirmation_verifier_agent.py`'s identical,
     directly-tested guarantee).
  c. If the Pro-tier call itself raises `reasoning.errors.
     GeminiCallFailed`, this is caught explicitly (never a bare
     `except:`) and resolved to `confirmed=False` — an unreadable model
     outcome is never treated as an implicit approval. This is meaningful
     error handling with a real safety consequence (fail closed), not a
     swallowed exception (gharos-standards rule 7's actual requirement).

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST` entry "A68").

*Forbidden:* **treating silence or ambiguity as approval** (see above —
structural, not conventional). `ConfirmationResult` itself carries no
`risk_tier`/`authorized` field and this module holds no `RiskTier`
import at all — whether an R3 request may proceed off a `confirmed=True`
result is the Approval Gate / voice orchestrator's decision (E3, next
wave), never this type's own concern (ADR-020 Decision 5, item 3: "R3 is
never approved by voice alone"). Imports nothing from `app.arbitration` —
see `backend/tests/test_voice_agents_arbitration_boundary.py`.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.errors import GeminiCallFailed
from ...reasoning.gemini_client import GeminiClient
from .affirmatives import check_affirmative
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_bool, require_float, require_str
from .types import ConfirmationEvaluationRequest, ConfirmationResult, ReadbackRequest, ReadbackResult

AGENT_ID = AgentId("A68")


def _amounts_block(request: ReadbackRequest) -> str:
    lines = [
        f'- {span.original_text!r} -> {span.amount_display} (must appear verbatim in the read-back)'
        for span in request.amount_spans
    ]
    return "\n".join(lines) if lines else "(no amounts to confirm)"


def _names_block(request: ReadbackRequest) -> str:
    lines = [
        f"- {ref.display_name}, {ref.relationship_to_speaker} (must appear with this relationship)"
        for ref in request.name_references
    ]
    return "\n".join(lines) if lines else "(no names to confirm)"


def _dates_block(request: ReadbackRequest) -> str:
    lines = [f"- {span.normalized_text}" for span in request.date_spans]
    return "\n".join(lines) if lines else "(no dates/times to confirm)"


class ConfirmationAgent:
    """A68 Confirmation Agent. Dependency-injected on a `GeminiClient`
    only — no `GraphReader`, no tool of any kind."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def generate_readback(self, request: ReadbackRequest) -> ReadbackResult:
        """Generates a real, spoken-ready read-back for `request`.

        Args:
            request: everything requiring confirmation for this turn —
                real, already-normalised amount/date spans and
                caller-resolved name references.

        Returns:
            A `ReadbackResult` whose `readback_text` is structurally
            guaranteed to contain every required amount's digit-grouped
            display string and every required name-plus-relationship.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or the produced
                `readback_text` is missing a required amount or name
                fact.
        """
        prompt = load_prompt("A68")
        rendered = prompt.text.format(
            speaker_language=request.speaker_language,
            intent_summary=request.intent.target_summary,
            amounts_block=_amounts_block(request),
            names_block=_names_block(request),
            dates_block=_dates_block(request),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        readback_text = require_str(parsed, "readback_text", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)

        for span in request.amount_spans:
            if span.amount_display is None:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"amount span {span.original_text!r} has no resolved amount_display to read back",
                    raw_text=readback_text,
                )
            if span.amount_display not in readback_text:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=(
                        f"read-back is missing the required digit-grouped amount "
                        f"{span.amount_display!r} (spec §14.6 rule 2)"
                    ),
                    raw_text=readback_text,
                )

        for ref in request.name_references:
            if ref.display_name not in readback_text or ref.relationship_to_speaker not in readback_text:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=(
                        f"read-back is missing the required name+relationship "
                        f"'{ref.display_name}, {ref.relationship_to_speaker}' (spec §14.6 rule 3)"
                    ),
                    raw_text=readback_text,
                )

        return ReadbackResult(
            turn_id=request.turn_id,
            readback_text=readback_text,
            requires_affirmative=True,
            confidence=confidence,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            generated_at=datetime.now(UTC),
        )

    def evaluate_response(self, request: ConfirmationEvaluationRequest) -> ConfirmationResult:
        """Evaluates whether `request.spoken_response_text` is a real,
        explicit affirmative to a prior read-back.

        Args:
            request: the prior read-back text plus the household member's
                real spoken response (`None`/blank represents silence).

        Returns:
            A `ConfirmationResult`. `confirmed=True` is reachable **only**
            when a canonical affirmative phrase matched AND (when the
            semantic narrowing call ran) that call agreed it was a real,
            unqualified affirmative. See module docstring for the full
            structural argument.
        """
        now = datetime.now(UTC)
        matched_phrase = check_affirmative(request.spoken_response_text, language=request.speaker_language)

        if matched_phrase is None:
            reason = (
                "no response received (silence)"
                if not (request.spoken_response_text or "").strip()
                else "response did not match any enumerated affirmative phrase"
            )
            return ConfirmationResult(
                turn_id=request.turn_id,
                confirmed=False,
                reason=reason,
                matched_affirmative_phrase=None,
                model_tier="deterministic",
                prompt_version="n/a",
                invocation_id=uuid.uuid4().hex,
                evaluated_at=now,
            )

        prompt = load_prompt("A68_EVALUATE")
        rendered = prompt.text.format(
            readback_text=request.readback_text,
            spoken_response_text=request.spoken_response_text,
            matched_phrase=matched_phrase,
        )
        try:
            call_result = self._gemini_client.generate_structured(
                agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
            )
        except GeminiCallFailed:
            # Fail closed, never open — an unreadable model outcome is
            # never treated as an implicit approval (see module docstring).
            return ConfirmationResult(
                turn_id=request.turn_id,
                confirmed=False,
                reason="semantic verification unavailable — treated as not confirmed",
                matched_affirmative_phrase=matched_phrase,
                model_tier="deterministic",
                prompt_version="n/a",
                invocation_id=uuid.uuid4().hex,
                evaluated_at=now,
            )

        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        # Deliberately reads ONLY `genuinely_affirmative` and
        # `explanation` — never a "confirmed" key of any kind (see module
        # docstring for why this is structural, not conventional).
        genuinely_affirmative = require_bool(parsed, "genuinely_affirmative", agent_id=AGENT_ID)
        explanation = require_str(parsed, "explanation", agent_id=AGENT_ID)

        return ConfirmationResult(
            turn_id=request.turn_id,
            confirmed=genuinely_affirmative,
            reason=explanation,
            matched_affirmative_phrase=matched_phrase,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            evaluated_at=now,
        )


__all__ = ["AGENT_ID", "ConfirmationAgent"]
