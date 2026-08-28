"""A54 — Voice Call Agent's conversation engine (spec §13.3, §13.6, §15.2,
PHASES.md Phase 10).

*Responsibility:* conduct the actual multi-turn conversation against the
sandbox counterparty, enforcing `app.agents.concierge.types.
CallBrief`'s authorised bounds turn by turn. *Model tier:* Pro-tier
realtime (`A54` is on `app.reasoning.model_router.PRO_TIER_ALLOWLIST` —
confirmed present before writing this module). *Forbidden* (spec §15.2
A54's own forbidden list, enforced structurally below, not by prompt
instruction alone): agreeing outside authorised bounds; guessing answers;
failing to disclose it is automated.

## Why this module holds no action credential

This class never imports `contracts.tools.ApprovalGatedTool` or anything
under `backend/app/arbitration/` — it is plain reasoning-and-decision code
that produces a `app.agents.concierge.types.
CallConversationResult` (data), never a call placed. The actual T5
gated tool that *may* run this engine — only once approved —
is `app.arbitration.voice_call_tool.VoiceCallTool`, this module's sibling
under `backend/app/arbitration/`, which is the only module in this
codebase permitted to import both this engine and `ApprovalGatedTool`
together. This split is why `A54` needing a live Pro-tier call does not
conflict with "a reasoning agent must have literally no importable path
to `contracts.tools.ApprovalGatedTool`" (spec §16.3 invariant 2,
`.claude/skills/gharos-tool-permissions/SKILL.md`) — this module is the
reasoning half; `voice_call_tool.py` is the only caller with both this
engine and the gate.

## Disclosure — structurally guaranteed, not a prompt instruction

Gate 10: "Disclosure on every call, cannot be disabled." The very first
turn of every call this engine ever runs is `_DISCLOSURE_OPENING`, a
plain Python f-string this module assembles from `CallBrief` fields —
**no Gemini call is made to produce it.** The model is never given a
chance to phrase, skip, soften, or "forget" turn zero; it does not see the
call at all until turn zero already exists in the transcript. See
`backend/tests/test_voice_call_agent.py`'s
`TestDisclosureCannotBeSkipped` for the adversarial proof: even a
fake Gemini client wired to actively refuse/omit disclosure cannot change
what turn zero says, because the model is never asked.

## Bounds enforcement — decide first, phrase second

Every turn, `_decide_next_action` computes what happens next as **plain,
deterministic code** over `CallBrief.date_range` / `price_ceiling` /
`disclosable_facts` / `must_not_answer` and the counterparty's structured
`CounterpartyTurnSignal` — never by asking the model to judge whether
something is in bounds or answerable. A live Pro-tier call
(`_phrase_utterance`) only ever *narrates* an already-locked-in decision
category in natural language; if that call fails, a plain deterministic
template is used instead (mirrors `app.arbitration.escalation_agent.
EscalationAgent`'s established "template fallback, never drop the
escalation" precedent) — the substantive outcome (`claimed_slot`,
`out_of_bounds_encountered`, `requires_human_callback`) is identical
either way, because it never depended on the model's phrasing to begin
with. This is what makes "never agrees outside bounds" and "never
guesses" structural rather than a documentation promise.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiClient

from .sandbox_counterparty import SandboxCounterparty
from .types import (
    CallBrief,
    CallConversationResult,
    CallerAction,
    CallerTurnDecision,
    CallTurn,
)

AGENT_ID = AgentId("A54")

logger = structlog.get_logger(__name__)

_MAX_EXCHANGES = 6
"""A real turn budget — mirrors a real phone call: this is not an
unbounded loop. Exceeding it without a resolved outcome routes to human
callback (`CallerAction.END_CALL_EXHAUSTED`), never an infinite call."""

_MIN_DISCLOSABLE_KEYWORD_LEN = 4
"""Words shorter than this (articles, "the", "for", ...) are never
treated as meaningful overlap for `_topic_is_disclosable`'s keyword
check — see that function's own docstring for the full, honestly-stated
heuristic and why it fails closed."""

_OUT_OF_BOUNDS_CALLBACK_LINE = "I'm not able to confirm that on this call — I'll need to check and call back."
"""Spec §13.3's exact required behaviour, verbatim: "Out-of-bounds
request -> 'I'll need to confirm and call back.'" Deterministic, code-
composed — never phrased by the model, so a slot/price outside bounds can
never be worded into an accidental agreement."""

_TAKE_MESSAGE_LINE = (
    "I don't have that information to hand — let me take a message and someone will confirm with you."
)
"""Spec §13.6: "Clinic asks something it can't answer -> never guess, take
a message, escalate." Deterministic, code-composed, for the same reason
as `_OUT_OF_BOUNDS_CALLBACK_LINE`."""


def _disclosure_opening(brief: CallBrief) -> str:
    """Turn zero of every call — see module docstring. Pure string
    formatting; makes no model call and can raise nothing that depends on
    a live service."""
    preferred = brief.preferred_slots[0].strftime("%A %B %d at %I:%M %p") if brief.preferred_slots else None
    slot_clause = f" I'd like to ask about {preferred}, if that's available." if preferred else ""
    return (
        "Hello — this is an automated assistant calling on behalf of a household, "
        f"regarding: {brief.objective}.{slot_clause}"
    )


def _slot_within_bounds(slot: datetime, date_range: tuple[datetime, datetime]) -> bool:
    start, end = date_range
    return start <= slot <= end


def _topic_is_disclosable(
    question: str, disclosable_facts: tuple[str, ...], must_not_answer: tuple[str, ...]
) -> bool:
    """Deterministic, keyword-overlap heuristic — **fails closed**. A
    question is only ever treated as answerable when a meaningful
    (>= `_MIN_DISCLOSABLE_KEYWORD_LEN`-character) word from it also
    appears in some `disclosable_facts` entry, AND no word from it matches
    a `must_not_answer` entry (checked first — `must_not_answer` always
    wins over an incidental disclosable-facts overlap).

    **Honestly stated limitation, not hidden:** this is keyword matching,
    not semantic understanding — it cannot tell "what's the patient's date
    of birth" is about `disclosable_facts=("patient's full name",)` unless
    a literal word overlaps. That is deliberate: spec's own "never guess"
    discipline for A54 (mirroring A13 Constraint Checker's "ambiguous ->
    escalate, never guess") is safer served by a heuristic that
    occasionally escalates a genuinely-answerable question than by one
    that ever silently answers an unauthorised one. A28/A13-style
    semantic Pro-tier judgment was considered and rejected here for
    exactly this reason — see this phase's final report's judgment-call
    list.
    """

    def _keywords(text: str) -> set[str]:
        return {
            word.strip(".,?!:;'\"").lower()
            for word in text.split()
            if len(word.strip(".,?!:;'\"")) >= _MIN_DISCLOSABLE_KEYWORD_LEN
        }

    question_words = _keywords(question)
    for forbidden in must_not_answer:
        if question_words & _keywords(forbidden):
            return False
    for fact in disclosable_facts:
        if question_words & _keywords(fact):
            return True
    return False


def _price_within_bounds(price: float, price_ceiling: float | None) -> bool:
    return price_ceiling is None or price <= price_ceiling


def _decide_next_action(
    *,
    brief: CallBrief,
    latest_signal_offered_slot: datetime | None,
    latest_signal_question: str | None,
    latest_signal_quoted_price: float | None,
    remaining_preferred_slots: tuple[datetime, ...],
) -> CallerTurnDecision:
    """The one place bounds/disclosability are decided — plain code, no
    model call. See module docstring. Price is checked exactly the way a
    slot is (spec §13.3: "a requested slot/price outside date_range/price_
    ceiling triggers... never an agreement") — checked first, since a
    quote outside the authorised ceiling makes any slot on the same turn
    moot regardless of whether that slot itself would have been in
    bounds."""
    if latest_signal_question is not None:
        if not _topic_is_disclosable(latest_signal_question, brief.disclosable_facts, brief.must_not_answer):
            return CallerTurnDecision(action=CallerAction.TAKE_MESSAGE_ESCALATE, target_slot=None)

    if latest_signal_quoted_price is not None:
        if not _price_within_bounds(latest_signal_quoted_price, brief.price_ceiling):
            return CallerTurnDecision(action=CallerAction.DECLINE_OUT_OF_BOUNDS_CALLBACK, target_slot=None)

    if latest_signal_offered_slot is not None:
        if _slot_within_bounds(latest_signal_offered_slot, brief.date_range):
            return CallerTurnDecision(action=CallerAction.ACCEPT_SLOT, target_slot=latest_signal_offered_slot)
        return CallerTurnDecision(action=CallerAction.DECLINE_OUT_OF_BOUNDS_CALLBACK, target_slot=None)

    if remaining_preferred_slots:
        return CallerTurnDecision(action=CallerAction.REQUEST_SLOT, target_slot=remaining_preferred_slots[0])

    if brief.fallback_acceptable:
        # Nothing preferred left to name; ask generically for anything within the authorised
        # date range — the counterparty's next offer (if any) is still bounds-checked above.
        return CallerTurnDecision(action=CallerAction.REQUEST_SLOT, target_slot=None)

    return CallerTurnDecision(action=CallerAction.DECLINE_OUT_OF_BOUNDS_CALLBACK, target_slot=None)


class VoiceCallConversationEngine:
    """A54's conversation engine. Dependency-injected on a `GeminiClient`
    only — no graph, no tool, no idempotency store; those belong to
    `app.arbitration.voice_call_tool.VoiceCallTool`, which wraps this
    class."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def run_conversation(
        self, *, brief: CallBrief, counterparty: SandboxCounterparty
    ) -> CallConversationResult:
        """Runs one full call, turn zero (disclosure) through resolution
        or turn-budget exhaustion. Never raises for an in-call event (a
        declined call, an out-of-bounds offer, an unanswerable question)
        — those are all outcomes recorded on the returned
        `CallConversationResult`, never exceptions, matching spec §13.6's
        "never a guess, never fabricated" framing as *reported outcomes*.
        Only a genuine infrastructure failure
        (`app.reasoning.errors.GeminiCallFailed` from the counterparty's
        own call) propagates, since a call that could not even reach the
        counterparty is a real failure, not an in-call branch.
        """
        opening = _disclosure_opening(brief)
        turns: list[CallTurn] = [CallTurn(speaker="caller", utterance=opening, turn_index=0)]
        latest_caller_utterance = opening
        remaining_preferred = list(brief.preferred_slots)

        out_of_bounds_encountered = False
        requires_human_callback = False
        claimed_slot: datetime | None = None
        outcome_summary = ""

        for _ in range(_MAX_EXCHANGES):
            signal = counterparty.respond(
                conversation_so_far=tuple(turns), latest_caller_utterance=latest_caller_utterance
            )
            turns.append(CallTurn(speaker="counterparty", utterance=signal.utterance, turn_index=len(turns)))

            if signal.declines_call:
                requires_human_callback = True
                outcome_summary = (
                    f"{counterparty.persona.clinic_name} declined to continue once told this was an "
                    "automated caller — abandoned gracefully; needs human follow-up."
                )
                break

            if (
                remaining_preferred
                and signal.offered_slot is None
                and remaining_preferred[0] in (brief.preferred_slots[:1] if brief.preferred_slots else ())
            ):
                # The counterparty did not offer the just-requested first-preferred slot at all
                # (e.g. said it plainly is unavailable) — advance past it so the next request
                # tries the following preferred slot rather than repeating the same one.
                if len(turns) > 2:  # only after we've actually asked at least once
                    remaining_preferred = remaining_preferred[1:]

            decision = _decide_next_action(
                brief=brief,
                latest_signal_offered_slot=signal.offered_slot,
                latest_signal_question=signal.asks_question,
                latest_signal_quoted_price=signal.quoted_price,
                remaining_preferred_slots=tuple(remaining_preferred),
            )

            if decision.action is CallerAction.ACCEPT_SLOT:
                assert decision.target_slot is not None
                claimed_slot = decision.target_slot
                utterance = self._phrase(
                    decision=decision, context=f"accept the offered slot {decision.target_slot.isoformat()}"
                )
                turns.append(CallTurn(speaker="caller", utterance=utterance, turn_index=len(turns)))
                outcome_summary = (
                    f"Booked with {counterparty.persona.clinic_name} for {claimed_slot.isoformat()}."
                )
                break

            if decision.action is CallerAction.DECLINE_OUT_OF_BOUNDS_CALLBACK:
                out_of_bounds_encountered = True
                requires_human_callback = True
                turns.append(
                    CallTurn(speaker="caller", utterance=_OUT_OF_BOUNDS_CALLBACK_LINE, turn_index=len(turns))
                )
                outcome_summary = (
                    f"{counterparty.persona.clinic_name} could only offer something outside the "
                    "authorised date range/price ceiling — declined and offered a callback rather than "
                    "agreeing."
                )
                break

            if decision.action is CallerAction.TAKE_MESSAGE_ESCALATE:
                requires_human_callback = True
                turns.append(CallTurn(speaker="caller", utterance=_TAKE_MESSAGE_LINE, turn_index=len(turns)))
                outcome_summary = (
                    f"{counterparty.persona.clinic_name} asked something outside the disclosable facts "
                    f"list ('{signal.asks_question}') — took a message instead of guessing."
                )
                break

            # REQUEST_SLOT — continue the loop with a new caller turn.
            context = (
                f"ask for the {decision.target_slot.isoformat()} slot"
                if decision.target_slot is not None
                else "ask for the earliest available slot within the authorised date range"
            )
            utterance = self._phrase(decision=decision, context=context)
            turns.append(CallTurn(speaker="caller", utterance=utterance, turn_index=len(turns)))
            latest_caller_utterance = utterance
        else:
            requires_human_callback = True
            outcome_summary = (
                "Call exceeded its turn budget without a resolved outcome — escalate to a human."
            )

        logger.info(
            "concierge.a54.call_completed",
            claimed_slot=claimed_slot.isoformat() if claimed_slot is not None else None,
            out_of_bounds_encountered=out_of_bounds_encountered,
            requires_human_callback=requires_human_callback,
            turn_count=len(turns),
        )
        return CallConversationResult(
            turns=tuple(turns),
            claimed_slot=claimed_slot,
            claimed_outcome_summary=outcome_summary,
            out_of_bounds_encountered=out_of_bounds_encountered,
            requires_human_callback=requires_human_callback,
        )

    def _phrase(self, *, decision: CallerTurnDecision, context: str) -> str:
        """Narrates an already-decided `decision` in natural language via
        a real Pro-tier call. **Never asked to decide anything** — only to
        phrase what code already locked in. On failure, falls back to a
        plain deterministic sentence (mirrors `EscalationAgent`'s template
        fallback) so a live call never stalls on a transient model
        failure; the substantive outcome is unaffected either way, since
        `context`/`decision.target_slot` — not this method's return value
        — drive `run_conversation`'s bookkeeping."""
        prompt = (
            "You are speaking on a phone call as an automated household assistant, mid-conversation "
            f"with a service provider. In one short, natural, spoken sentence, {context}. "
            "Respond with the sentence only — no quotation marks, no preamble."
        )
        try:
            call_result = self._gemini_client.generate_text(
                agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=prompt
            )
        except GeminiCallFailed as exc:
            logger.warning("concierge.a54.phrasing_call_failed", reason=str(exc))
            return f"Could you help me {context}?"
        return call_result.text.strip()


__all__ = ["AGENT_ID", "VoiceCallConversationEngine"]
