"""A67 — Voice Intent Classifier (spec §14.5, §14.6, §15.11, PHASES.md
Phase 13, ADR-020) — E2's `backend/app/agents/voice/`.

*Responsibility:* classify one normalised, per-span-tagged voice turn into
exactly one of spec §14.5's seven classes (`capture` / `intention` /
`command` / `query` / `approval` / `decision_trigger` / `correction`) —
or into the one Phase 14.5 addition, `ingest.scan_mailbox` (ADR-023 §7,
a read-only "scan my Gmail and Outlook" ingestion trigger) — each with
its own distinct downstream handling rule:

| Class | Downstream handling this output enables |
|---|---|
| `capture` | Routes to the Consequence Engine as a source — full implication pipeline |
| `intention` | Routes to Intention->Action — blocker diagnosis follows |
| `command` | R0/R1 — execute, confirm verbally |
| `query` | Graph query; answer, optionally with the path |
| `approval` | R2/R3 — **mandatory read-back confirmation, spec §14.6** |
| `decision_trigger` | Convenes the Council — **never resolved by voice itself** |
| `correction` | Feeds A5 Entity Resolution's alias learning |
| `ingest.scan_mailbox` | Routes to `on_scan_mailbox`; never a tool/gate; no `risk_tier` (ADR-023 §7) |

**`ingest.scan_mailbox` is decided deterministically, independent of the
model call** (`_is_scan_mailbox_request`, a pure function over the turn's
own tokens — a scan/check/read verb co-occurring with a mailbox noun, or
one of a small set of fixed multi-word phrases, English and code-mixed).
When it matches, `classify()` returns immediately with
`model_tier="deterministic"` and makes **no Gemini call at all** — the
same "nothing to narrate -> no model call" discipline A68's
`evaluate_response` and A55 already follow. The A67 prompt (v2+) also
describes this intent so the model path agrees on any phrasing the token
match does not cover, but the deterministic path is authoritative and
runs first. This mirrors `_requires_confirmation`'s pure-function style:
a real structural signal, never model discretion.

**`risk_tier` is populated only for `command` (R0/R1), `approval`
(R2/R3), and `decision_trigger`** — and for `decision_trigger` it is
**always, structurally, `RiskTier.R4_ESCALATE_ONLY`**, never taken from
the model's own output at all (spec §14.5: "R4 decisions are never
resolved by voice" — this is the one place in this module where the
model's opinion is irrelevant by design, not merely double-checked). For
`command`/`approval`, the model's reported tier is validated against the
*only* two tiers that class is permitted (`{R0,R1}` / `{R2,R3}`
respectively) — a report outside that set raises `errors.
ModelResponseMalformed` rather than being silently accepted.

**`requires_confirmation` is computed deterministically in code**
(`_requires_confirmation`), from real structural signals (an amount span
is present; a committing date/time is present on a `command`/`approval`
turn; the resolved `risk_tier` is R2 or R3) plus two narrow model-reported
booleans this agent cannot determine from spans alone (whether a hard
constraint's person-name is involved; whether this is a staff
attendance/salary entry) — never left to the model's own end-to-end
discretion. This is spec §14.6's mandatory-read-back list made testable
directly, independent of prompt wording.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST` entry "A67").

*Forbidden:* **executing anything — this agent classifies and routes
only.** Holds zero tool of any tier above T0/T2 (in practice: holds no
tool at all — there is nothing for this agent to do with one), and
imports nothing from `app.arbitration` — see
`backend/tests/test_voice_agents_arbitration_boundary.py`'s direct
AST-based proof.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from contracts.actions import RiskTier
from contracts.agents import ModelTier
from contracts.graph_types import AgentId

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_bool, require_float, require_str
from .types import NormalizedSpan, VoiceIntentClass, VoiceIntentRequest, VoiceIntentResult

AGENT_ID = AgentId("A67")

_COMMAND_TIERS: frozenset[str] = frozenset({RiskTier.R0_SILENT.value, RiskTier.R1_NOTIFY.value})
_APPROVAL_TIERS: frozenset[str] = frozenset({RiskTier.R2_APPROVE.value, RiskTier.R3_EXPLICIT_APPROVE.value})

# ---------------------------------------------------------------------------
# `ingest.scan_mailbox` — deterministic detection (ADR-023 §7)
# ---------------------------------------------------------------------------

_TOKEN_PATTERN = re.compile(r"\w+", re.UNICODE)

_SCAN_VERB_TOKENS: frozenset[str] = frozenset(
    {
        # English
        "scan",
        "check",
        "read",
        "fetch",
        "pull",
        "sync",
        "import",
        "go",  # "go through my inbox"
        # Romanised Hindi/Marathi imperatives
        "padho",
        "padh",
        "dekho",
        "dekh",
        "nikaal",
        "nikaalo",
        "nikal",
        "nikalo",
    }
)
"""Verb tokens that, co-occurring with a mailbox noun in the same turn,
mark a mailbox-scan request. Deliberately generous: a false positive
triggers only a read-only ingestion run (no action, no tool, no
approval — ADR-023 §7), while a false negative silently drops a real
request. The A67 prompt (v2+) is the model-path backstop for phrasings
these tokens miss."""

_MAILBOX_NOUN_TOKENS: frozenset[str] = frozenset(
    {
        "gmail",
        "email",
        "emails",
        "mail",
        "mails",
        "inbox",
        "mailbox",
        "outlook",
        "मेल",
        "ईमेल",
        "इनबॉक्स",
    }
)
"""Nouns that name a mailbox. `e-mail` tokenises to `e` + `mail`; `mail`
is here, so it still matches."""

_SCAN_MAILBOX_PHRASES: tuple[str, ...] = (
    "scan last 24 hours",
    "scan the last 24 hours",
    "scan my last 24 hours",
    "last 24 hours of mail",
    "last 24 hours of email",
    "scan karo",
    "check karo",
    "scan kar do",
)
"""Fixed multi-word phrases that mean "scan the mailbox" without fitting
the verb+noun co-occurrence shape (e.g. a bare "scan karo" following a
turn that already established the mailbox context, or an explicit
"last 24 hours" window request). Matched against the space-joined,
case-folded token stream."""


def _is_scan_mailbox_request(raw_text: str) -> bool:
    """Pure, deterministic test for A67's `ingest.scan_mailbox` intent —
    the read-only "scan my Gmail and Outlook" trigger (ADR-023 §7).

    Runs BEFORE, and independently of, any model call (mirrors
    `_requires_confirmation`'s pure-function discipline and A68's
    "structural check resolves it -> no Gemini call" pattern). Returns
    `True` when the turn's own tokens contain a scan/check/read verb
    together with a mailbox noun, or contain one of `_SCAN_MAILBOX_
    PHRASES`. Case- and script-tolerant; never consults the model.

    Args:
        raw_text: the turn's normalised transcript, exactly as A65
            produced it (code-mixed, not "cleaned up").

    Returns:
        `True` iff this turn is a mailbox-scan request.
    """
    folded = raw_text.casefold()
    tokens = _TOKEN_PATTERN.findall(folded)
    if not tokens:
        return False
    token_set = set(tokens)
    if token_set & _SCAN_VERB_TOKENS and token_set & _MAILBOX_NOUN_TOKENS:
        return True
    joined = " ".join(tokens)
    return any(phrase in joined for phrase in _SCAN_MAILBOX_PHRASES)


@dataclass(frozen=True, slots=True)
class _ConfirmationSignals:
    """Every real signal `_requires_confirmation` combines — a plain,
    directly-testable value type so the read-back rule itself
    (`backend/tests/test_voice_intent_classifier_agent.py`) can be
    exercised without going through a full model call for every case."""

    intent: VoiceIntentClass
    risk_tier: RiskTier | None
    has_amount_span: bool
    has_committing_date_span: bool
    involves_hard_constraint_name: bool
    involves_staff_attendance_or_salary: bool


def _requires_confirmation(signals: _ConfirmationSignals) -> bool:
    """Spec §14.6's mandatory-read-back list, as a pure deterministic
    function: "any amount of money; any person's name where a hard
    constraint is involved; any date or time being committed to; any
    approval of an R2/R3 action; any staff attendance or salary entry."
    """
    if signals.has_amount_span:
        return True
    if signals.involves_hard_constraint_name:
        return True
    if signals.involves_staff_attendance_or_salary:
        return True
    if signals.risk_tier in (RiskTier.R2_APPROVE, RiskTier.R3_EXPLICIT_APPROVE):
        return True
    if signals.has_committing_date_span and signals.intent in (
        VoiceIntentClass.COMMAND,
        VoiceIntentClass.APPROVAL,
    ):
        return True
    return False


def _resolve_risk_tier(*, intent: VoiceIntentClass, raw_risk_tier: str | None) -> RiskTier | None:
    """Resolves the structural risk tier for `intent`, validating the
    model's reported tier against the only set that class permits.

    Raises:
        errors.ModelResponseMalformed: `intent` is `COMMAND` or `APPROVAL`
            and `raw_risk_tier` is missing or outside the tier set that
            class permits.
    """
    if intent is VoiceIntentClass.DECISION_TRIGGER:
        # Never taken from the model — spec §14.5: "R4 decisions are
        # never resolved by voice."
        return RiskTier.R4_ESCALATE_ONLY

    if intent is VoiceIntentClass.COMMAND:
        if raw_risk_tier not in _COMMAND_TIERS:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"intent 'command' requires risk_tier in {_COMMAND_TIERS!r}, got {raw_risk_tier!r}",
                raw_text=str(raw_risk_tier),
            )
        return RiskTier(raw_risk_tier)

    if intent is VoiceIntentClass.APPROVAL:
        if raw_risk_tier not in _APPROVAL_TIERS:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"intent 'approval' requires risk_tier in {_APPROVAL_TIERS!r}, got {raw_risk_tier!r}",
                raw_text=str(raw_risk_tier),
            )
        return RiskTier(raw_risk_tier)

    # capture / intention / query / correction / ingest.scan_mailbox
    # never carry a risk tier from this classifier — their eventual tier
    # (if any) is decided downstream by the subsystem they route to, and
    # ingest.scan_mailbox carries no tier at all (ADR-023 §7).
    return None


def _has_kind(spans: tuple[NormalizedSpan, ...], kind: str) -> bool:
    return any(span.kind == kind for span in spans)


class VoiceIntentClassifierAgent:
    """A67 Voice Intent Classifier. Dependency-injected on a
    `GeminiClient` only — no `GraphReader`, no tool of any kind."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def classify(self, request: VoiceIntentRequest) -> VoiceIntentResult:
        """Classifies `request` into one of spec §14.5's seven intent
        classes, or into `ingest.scan_mailbox` (ADR-023 §7).

        A turn whose text is a mailbox-scan request
        (`_is_scan_mailbox_request`) is resolved to
        `VoiceIntentClass.INGEST_SCAN_MAILBOX` deterministically, with
        NO Gemini call — `risk_tier` `None`, `requires_confirmation`
        `False`, `model_tier` `"deterministic"`. Every other turn takes
        the model path unchanged.

        Args:
            request: A65's real normalised spans for one turn, plus the
                caller-resolved speaker context and (optionally) a plain
                summary of the immediately preceding turn.

        Returns:
            A `VoiceIntentResult`. See module docstring for `risk_tier`
            and `requires_confirmation` policy.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, reported an intent
                outside the permitted classes, or reported a
                `command`/`approval` risk tier outside the set that class
                permits.
        """
        if _is_scan_mailbox_request(request.raw_text):
            prompt = load_prompt("A67")
            return VoiceIntentResult(
                turn_id=request.turn_id,
                intent=VoiceIntentClass.INGEST_SCAN_MAILBOX,
                risk_tier=None,
                target_summary="scan the household mailbox (Gmail/Outlook) for the last 24 hours",
                requires_confirmation=False,
                reasoning=(
                    "deterministic phrase match on a mailbox-scan request — resolved without a "
                    "model call (ADR-023 §7); a read-only ingestion trigger, never an action"
                ),
                confidence=1.0,
                model_tier="deterministic",
                prompt_version=prompt.version,
                invocation_id=uuid.uuid4().hex,
                classified_at=datetime.now(UTC),
            )

        spans_block = "\n".join(
            f'- "{span.normalized_text}" (kind={span.kind}, language={span.language})'
            for span in request.normalized_spans
        )
        prompt = load_prompt("A67")
        rendered = prompt.text.format(
            raw_text=request.raw_text,
            spans_block=spans_block or "(no spans)",
            prior_turn_summary=request.prior_turn_summary or "(none — this is a fresh turn)",
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        intent_raw = require_str(parsed, "intent", agent_id=AGENT_ID)
        try:
            intent = VoiceIntentClass(intent_raw)
        except ValueError as exc:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"intent {intent_raw!r} is not one of A67's permitted classes",
                raw_text=call_result.text,
            ) from exc

        raw_risk_tier = parsed.get("risk_tier")
        risk_tier = _resolve_risk_tier(
            intent=intent, raw_risk_tier=raw_risk_tier if isinstance(raw_risk_tier, str) else None
        )

        target_summary = require_str(parsed, "target_summary", agent_id=AGENT_ID)
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID)
        involves_hard_constraint_name = require_bool(
            parsed, "involves_hard_constraint_name", agent_id=AGENT_ID, default=False
        )
        involves_staff_attendance_or_salary = require_bool(
            parsed, "involves_staff_attendance_or_salary", agent_id=AGENT_ID, default=False
        )

        signals = _ConfirmationSignals(
            intent=intent,
            risk_tier=risk_tier,
            has_amount_span=_has_kind(request.normalized_spans, "amount"),
            has_committing_date_span=_has_kind(request.normalized_spans, "date"),
            involves_hard_constraint_name=involves_hard_constraint_name,
            involves_staff_attendance_or_salary=involves_staff_attendance_or_salary,
        )

        return VoiceIntentResult(
            turn_id=request.turn_id,
            intent=intent,
            risk_tier=risk_tier,
            target_summary=target_summary,
            requires_confirmation=_requires_confirmation(signals),
            reasoning=reasoning,
            confidence=confidence,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
            classified_at=datetime.now(UTC),
        )


__all__ = ["AGENT_ID", "VoiceIntentClassifierAgent"]
