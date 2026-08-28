"""The sandbox counterparty — a real, second, independently-reasoning LLM
agent standing in for "the dental clinic front desk" spec §13.7's own
worked example names (ADR-016, PHASES.md Phase 10 dispatch: "For the
demo, call a controlled/sandbox counterparty, not a real business").

**Why this is a real agent and not a canned response table (ADR-016):**
`A54`'s entire job this phase — enforcing pre-authorised bounds turn by
turn, never guessing an answer, detecting hostility and abandoning
gracefully — is only genuinely tested if the *other* side of the call
reasons for itself, from its own persona and its own state, independently
of A54's own code. A fixture the same engineer's code effectively writes
both sides of would make A54's branch-handling self-testing. This module
therefore makes a real Gemini call (Flash-tier — this is a test/demo
counterparty, not one of the 69 roster agents, so it has no entry in
`app.reasoning.model_router.PRO_TIER_ALLOWLIST` and must never request
`ModelTier.PRO`) every turn, and the calling agent (A54,
`voice_call_agent.py`) never controls or inspects this module's internal
`CounterpartyPersona` — it only ever sees the `CounterpartyTurnSignal`
this class's own `respond()` produces, exactly as a real caller only
hears what the other side of the phone line says.

**Honest scope note (ADR-016):** this is a real, live, multi-turn
text/transcript conversation — not synthesized audio. Nothing in this
module's prompts, variable names, or docstrings implies TTS/ASR exists;
`utterance` is text the counterparty "says," rendered as a transcript line
alongside A54's own turns, never as audio.

Four configurable variants (this phase's own dispatch instructions), each
a real behavioural difference in how the persona reasons about the same
caller utterances, not four different code paths in this module — the
variant only shapes the *prompt* (what this persona has been told to do);
the reasoning about any given turn is still a live model call.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from app.reasoning.gemini_client import GeminiClient

from .errors import ModelResponseMalformed
from .json_utils import optional_str, parse_json_response, require_bool
from .types import CallTurn, CounterpartyPersona, CounterpartyTurnSignal, CounterpartyVariant

AGENT_ID = AgentId("SANDBOX-COUNTERPARTY")
"""Deliberately not one of spec §15's 69 roster agent ids — this is a test
and demo double for the *other side* of the call, not a household-facing
agent. Never added to `model_router.PRO_TIER_ALLOWLIST`; this module only
ever requests `ModelTier.FLASH`, which needs no allowlist entry."""

logger = structlog.get_logger(__name__)

_VARIANT_INSTRUCTIONS: dict[CounterpartyVariant, str] = {
    CounterpartyVariant.COOPERATIVE: (
        "You are a normal, helpful, moderately busy front-desk staff member. You offer the earliest "
        "slot from your real available slots list that reasonably fits what the caller asked for. You "
        "answer routine questions (name, insurance, reason for visit) without complaint."
    ),
    CounterpartyVariant.FIRST_PREFERRED_SLOT_UNAVAILABLE: (
        "You are a normal, helpful front-desk staff member, but you are genuinely fully booked for "
        "whatever specific slot the caller asks for first. Say so plainly and honestly (do not "
        "apologise excessively), then offer the next real slot from your available slots list instead. "
        "If the caller asks again for a different slot, check your available slots list honestly."
    ),
    CounterpartyVariant.ASKS_OUT_OF_SCOPE_QUESTION: (
        "You are a normal, helpful front-desk staff member, but before you can offer any slot, your "
        "clinic's real policy requires you to ask the caller the exact question given to you below "
        "('your required question'). Ask it plainly, once, the first time it is your turn to speak. "
        "Only after the caller responds to it do you proceed to offering a slot from your available "
        "slots list."
    ),
    CounterpartyVariant.HOSTILE_TO_AUTOMATED_CALLERS: (
        "You are a front-desk staff member whose clinic has a firm policy against automated/robocall "
        "systems. As soon as the caller's very first turn identifies itself as an automated assistant "
        "calling on behalf of a household (which it always will, by law), you decline to continue the "
        "call. Say so briefly and plainly, then end the call — do not offer any slot, do not ask any "
        "further question. Set declines_call to true on this turn."
    ),
}

_PROMPT = """You are role-playing as {clinic_name}, a small business front desk, receiving an incoming \
phone call. Stay fully in character and respond only as this front desk would.

Your persona instructions: {variant_instructions}

Your real available appointment slots (only offer from this list, in ISO 8601): {available_slots}
{question_clause}
Conversation so far (most recent last):
{transcript}

The caller's latest turn: "{latest_caller_utterance}"

Respond with a single JSON object and nothing else, describing your next turn:
{{"utterance": "<what you say next, in character, one or two sentences>", \
"offered_slot_iso": "<ISO 8601 datetime you are offering this turn, or null if you are not offering one>", \
"declines_call": true or false, \
"asks_question": "<the exact question you are asking this turn, or null if you are not asking one>", \
"quoted_price": <a number if you are genuinely quoting a price this turn, otherwise null>}}

"offered_slot_iso" must be null unless you are genuinely offering a specific slot from your available \
slots list this turn. "declines_call" must be true only if you are ending the call due to hostility to \
automated callers (per your persona instructions above) — never for an ordinary "let me check" turn. \
"asks_question" must be null unless this turn is you asking the caller something. "quoted_price" must \
be null unless your persona instructions ask you to quote a price this turn."""


def _format_transcript(turns: tuple[CallTurn, ...]) -> str:
    if not turns:
        return "(nothing said yet)"
    return "\n".join(f"{turn.speaker}: {turn.utterance}" for turn in turns)


class SandboxCounterparty:
    """A real, second Gemini-backed agent — see module docstring. Holds
    its own `CounterpartyPersona`, never mutated by the caller between
    turns (the persona's `available_slots`/`out_of_scope_question` are
    fixed at construction, exactly as a real clinic's actual policy and
    calendar would not change mid-call)."""

    def __init__(self, *, gemini_client: GeminiClient, persona: CounterpartyPersona) -> None:
        self._gemini_client = gemini_client
        self._persona = persona

    @property
    def persona(self) -> CounterpartyPersona:
        return self._persona

    def respond(
        self, *, conversation_so_far: tuple[CallTurn, ...], latest_caller_utterance: str
    ) -> CounterpartyTurnSignal:
        """Produces this persona's next real, independently-reasoned turn.

        Raises:
            app.reasoning.errors.GeminiCallFailed: the live call itself
                failed — never silently reinterpreted as a cooperative or
                hostile turn (safety invariant #7's analogue: a failed
                counterparty call must surface as a failure to the caller,
                which routes it through the fallback ladder, not through a
                fabricated in-character response).
            errors.ModelResponseMalformed: the response could not be
                parsed into the expected JSON shape, or `offered_slot_iso`
                was present but not a valid ISO 8601 datetime.
        """
        question_clause = (
            f"\nYour required question this call, if not yet asked: {self._persona.out_of_scope_question}\n"
            if self._persona.out_of_scope_question is not None
            else ""
        )
        prompt = _PROMPT.format(
            clinic_name=self._persona.clinic_name,
            variant_instructions=_VARIANT_INSTRUCTIONS[self._persona.variant],
            available_slots=", ".join(slot.isoformat() for slot in self._persona.available_slots) or "(none)",
            question_clause=question_clause,
            transcript=_format_transcript(conversation_so_far),
            latest_caller_utterance=latest_caller_utterance,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=prompt
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        utterance = parsed.get("utterance")
        if not isinstance(utterance, str) or not utterance.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="missing/empty 'utterance'", raw_text=call_result.text
            )
        declines_call = require_bool(parsed, "declines_call", agent_id=AGENT_ID, default=False)
        asks_question = optional_str(parsed, "asks_question")
        offered_slot = self._parse_offered_slot(parsed.get("offered_slot_iso"), raw_text=call_result.text)
        quoted_price = self._parse_quoted_price(parsed.get("quoted_price"), raw_text=call_result.text)

        logger.info(
            "concierge.sandbox_counterparty.turn",
            variant=self._persona.variant.value,
            declines_call=declines_call,
            offered_slot=offered_slot.isoformat() if offered_slot is not None else None,
            asks_question=asks_question is not None,
            quoted_price=quoted_price,
        )
        return CounterpartyTurnSignal(
            utterance=utterance.strip(),
            offered_slot=offered_slot,
            declines_call=declines_call,
            asks_question=asks_question,
            quoted_price=quoted_price,
        )

    def _parse_offered_slot(self, raw: object, *, raw_text: str) -> datetime | None:
        if raw is None:
            return None
        if not isinstance(raw, str):
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="'offered_slot_iso' must be a string or null", raw_text=raw_text
            )
        try:
            return datetime.fromisoformat(raw)
        except ValueError as exc:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"'offered_slot_iso' is not valid ISO 8601: {raw!r}",
                raw_text=raw_text,
            ) from exc

    def _parse_quoted_price(self, raw: object, *, raw_text: str) -> float | None:
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, int | float):
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="'quoted_price' must be a number or null", raw_text=raw_text
            )
        return float(raw)


__all__ = ["AGENT_ID", "SandboxCounterparty"]
