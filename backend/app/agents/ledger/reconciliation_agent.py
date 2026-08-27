"""A28 — Reconciliation Agent (spec §10.3B, §10.5, §15.7).

*Responsibility:* match debits to series; detect novel recurrences
(silent-renewal finder), silent price changes, and duplicates; reconcile
dues; flag SMS-vs-ledger mismatches for the dispute branch (A32); and for
staff salary specifically, cross-check that a recorded
`LedgerEvent(kind=SALARY)` payment matches what A34/`app.solvers.
salary_calculator` actually computed as due — never computing the salary
figure itself (that is A34's explicit job this phase; see this module's
own docstring section below and `PHASES.md`'s Phase 7 scope note).

*Model tier:* Pro-tier for matching (spec §15.7: "does this messy raw
debit string belong to this known commitment's series" is a genuine fuzzy-
matching judgment call — `SUNRISE SOCIETY MAINT` vs `Sunrise Apartments
Society` is not a substring match). **Arithmetic is delegated to plain,
deterministic functions in this same module** (`_detect_price_change`,
`_detect_duplicates`, `_compare_figures`) — never to a model call. A run
that only exercises those deterministic checks makes no Gemini call at
all (`ReconciliationRunResult.model_tier == "deterministic"`); cost
discipline mirrors `constraint_checker.py`'s relevance prefilter and
`conflict_radar.py`'s "skip the Pro-tier call when there's nothing new to
judge" rule.

## READ-ONLY BY CONSTRUCTION — the architectural non-negotiable (spec §10.5)

This is not a docstring claim. `ReconciliationAgent.__init__` constructs
its own `app.tools.registry.ToolRegistry` with
`allowed_tiers=frozenset({PermissionTier.T0_READ})` — a hard construction-
time ceiling, not a convention this class merely intends to respect. Any
attempt to register a T3+ tool onto that registry (whether by this class's
own code or by a future edit) is rejected by `ToolRegistry.register` at
the moment of registration, proven adversarially in
`backend/tests/test_reconciliation_agent.py`. This class never accepts or
stores a raw `GraphReader`/`GraphWriter` — its only path to graph data is
`self._tool_registry.get("graph_reader").invoke(...)`, the same T0 surface
any other reasoning agent gets, so "A28 cannot move money" is checkable by
inspecting `ReconciliationAgent(...).tool_registry.tools()` directly,
without running the agent at all (Gate 7's literal CTO review item).

*Forbidden:* no communication, no payment — enforced by the tool registry
above, not by omission. *Failure:* a detected SMS-vs-ledger (or salary)
mismatch is reported as a `ReconciliationFinding` with
`requires_dispute_branch=True`; this module never attempts to decide which
figure is correct — that decision does not exist as a method on this
class, only "route to A32" does.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Literal, cast

import structlog
from contracts.actions import ActionResult
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import AgentId, LedgerEvent, LedgerEventKind, NodeId, RecurringCommitment
from contracts.repositories import GraphReader
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...solvers.salary_calculator import SalaryCalculationResult
from ...tools.graph_read_tool import GraphReadTool
from ...tools.registry import ToolRegistry
from .errors import CurrencyMismatch
from .json_utils import parse_json_response, require_bool, require_float, require_str
from .types import ReconciliationFinding, ReconciliationRequest, ReconciliationRunResult

AGENT_ID = AgentId("A28")

logger = structlog.get_logger(__name__)

_DUPLICATE_WINDOW = timedelta(hours=48)
"""Two DEBIT events on the same series within this window, for
(near-)identical amounts, are treated as a duplicate charge rather than a
legitimate re-billing — a household's normal cadence (monthly, weekly) is
always far longer than this."""

_DUPLICATE_AMOUNT_TOLERANCE = 0.01
"""Currency-unit tolerance for "the same amount" — absorbs float rounding,
never masks a genuinely different charge."""

_PRICE_CHANGE_MIN_ABS = 0.01
"""A `price_history` delta smaller than this is float noise, not a real
price change."""

_MISMATCH_ABS_TOLERANCE = 1.0
"""Absolute currency-unit tolerance for "the same figure" when comparing
two independently-sourced amounts (SMS vs ledger, recorded vs computed
salary). Real SMS/ledger/register figures for the *same* transaction do
not legitimately differ by more than rounding — anything beyond this
floor is a genuine discrepancy, not noise. A real product tunable, not a
guessed one: documented here exactly like `salary_calculator.py`'s two
explicit policy calls, open to a future CTO-approved change once real
mismatch data exists."""


def _detect_price_change(commitment: RecurringCommitment) -> ReconciliationFinding | None:
    """Deterministic — compares the two most recent `price_history`
    entries. Returns `None` when there are fewer than two entries, or the
    delta does not clear `_PRICE_CHANGE_MIN_ABS`."""
    if len(commitment.price_history) < 2:
        return None
    (_, old_price), (_, new_price) = commitment.price_history[-2:]
    delta = new_price - old_price
    if abs(delta) < _PRICE_CHANGE_MIN_ABS:
        return None
    change_pct = (delta / old_price * 100.0) if old_price else None
    pct_clause = f" ({'+' if delta > 0 else ''}{change_pct:.1f}%)" if change_pct is not None else ""
    return ReconciliationFinding(
        kind="price_change",
        commitment_id=commitment.id,
        subject_event_ids=(),
        explanation=f"{commitment.label}: price moved from {old_price:.2f} to {new_price:.2f}{pct_clause}",
        evidence={
            "old_price": f"{old_price:.2f}",
            "new_price": f"{new_price:.2f}",
            "change_pct": (f"{change_pct:.1f}%" if change_pct is not None else "n/a"),
        },
        confidence=1.0,
        requires_dispute_branch=False,
    )


def _detect_duplicates(
    *, commitment_id: NodeId, events: tuple[LedgerEvent, ...]
) -> tuple[ReconciliationFinding, ...]:
    """Deterministic — flags any two DEBIT events on the same series
    within `_DUPLICATE_WINDOW` for effectively the same amount."""
    debits = sorted(
        (event for event in events if event.kind is LedgerEventKind.DEBIT),
        key=lambda event: event.occurred_at,
    )
    findings: list[ReconciliationFinding] = []
    for i, earlier in enumerate(debits):
        for later in debits[i + 1 :]:
            gap = later.occurred_at - earlier.occurred_at
            if gap > _DUPLICATE_WINDOW:
                break  # sorted ascending — no later event in this inner loop can be closer
            if abs(earlier.amount - later.amount) <= _DUPLICATE_AMOUNT_TOLERANCE:
                findings.append(
                    ReconciliationFinding(
                        kind="duplicate",
                        commitment_id=commitment_id,
                        subject_event_ids=(earlier.id, later.id),
                        explanation=(
                            f"two debits of {earlier.amount:.2f} {gap} apart on the same series — "
                            "looks like a duplicate charge, not a legitimate re-billing"
                        ),
                        evidence={"amount": f"{earlier.amount:.2f}", "gap": str(gap)},
                        confidence=1.0,
                        requires_dispute_branch=False,
                    )
                )
    return tuple(findings)


def _compare_figures(
    *,
    kind: Literal["sms_ledger_mismatch", "dues_mismatch", "salary_mismatch"],
    reconciled_kind: Literal["salary_reconciled"] | None,
    amount_a: float,
    amount_b: float,
    currency_a: str,
    currency_b: str,
    commitment_id: NodeId | None,
    subject_event_ids: tuple[NodeId, ...],
    explanation_subject: str,
    label_a: str,
    label_b: str,
) -> ReconciliationFinding | None:
    """Deterministic comparison shared by the SMS-vs-ledger check and the
    salary cross-check. Returns `None` only when `reconciled_kind` is
    `None` and the figures match (the generic dues/SMS case: a clean match
    is simply nothing to report); when `reconciled_kind` is given (the
    salary cross-check), a clean match still produces a
    `"salary_reconciled"` finding — spec's own "compute [cross-check]
    staff salary" line names this as something A28 must actively confirm
    and record, not silently pass over.

    Raises:
        errors.CurrencyMismatch: `currency_a != currency_b` — comparing
            raw amounts across currencies without conversion would
            fabricate a discrepancy figure that means nothing.
    """
    if currency_a != currency_b:
        raise CurrencyMismatch(currency_a=currency_a, currency_b=currency_b, context=explanation_subject)
    diff = abs(amount_a - amount_b)
    mismatched = diff > _MISMATCH_ABS_TOLERANCE
    if not mismatched and reconciled_kind is None:
        return None
    finding_kind = kind if mismatched else reconciled_kind
    assert finding_kind is not None  # mismatched=True always sets `kind`; else reconciled_kind is not None
    return ReconciliationFinding(
        kind=finding_kind,
        commitment_id=commitment_id,
        subject_event_ids=subject_event_ids,
        explanation=(
            f"{explanation_subject}: {label_a}={amount_a:.2f} vs {label_b}={amount_b:.2f} "
            f"(diff {diff:.2f}) — {'mismatch, routed for human resolution' if mismatched else 'reconciled'}"
        ),
        evidence={f"{label_a}_amount": f"{amount_a:.2f}", f"{label_b}_amount": f"{amount_b:.2f}"},
        confidence=1.0,
        requires_dispute_branch=mismatched,
    )


class ReconciliationAgent:
    """A28 Reconciliation Agent. Read-only by construction — see this
    module's docstring."""

    def __init__(self, *, gemini_client: GeminiClient, graph_reader: GraphReader) -> None:
        """Args:
        gemini_client: used only for the Pro-tier matching pass
            (`match_unlinked_event`) — never for anything this module
            treats as arithmetic.
        graph_reader: wrapped immediately into a T0-only `GraphReadTool`
            and never stored directly on `self` — this class's only path
            to graph data from here on is `self._tool_registry`.
        """
        self._gemini_client = gemini_client
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T0_READ})
        )
        self._tool_registry.register(GraphReadTool(graph_reader=graph_reader))

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed so Gate 7's CTO review, and
        `backend/tests/test_reconciliation_agent.py`'s adversarial proof,
        can inspect this agent's registered tools directly — "any write
        capability fails the phase" is checkable against this property
        without running the agent at all."""
        return self._tool_registry

    def fetch_series(self, commitment_id: NodeId) -> tuple[LedgerEvent, ...]:
        """Fetches every LEDGER_EVENT belonging to `commitment_id`'s
        series, via the T0 `graph_reader` tool only.

        Raises:
            contracts.errors.ToolFailure: the underlying read failed —
                never reinterpreted as "no events" (safety invariant #7).
        """
        tool = self._tool_registry.get("graph_reader")
        assert isinstance(tool, GraphReadTool)  # registered by this class's own __init__, always present
        result: ActionResult[object] = tool.invoke(operation="series", commitment_id=str(commitment_id))
        if not result.ok:
            raise ToolFailure(
                tool_name="graph_reader", reason=result.error or "series lookup failed", retryable=True
            )
        if result.value is None:
            return ()
        events = cast("tuple[object, ...]", result.value)
        return tuple(item for item in events if isinstance(item, LedgerEvent))

    def match_unlinked_event(
        self, *, event: LedgerEvent, commitment: RecurringCommitment
    ) -> ReconciliationFinding | None:
        """Pro-tier judgment: does `event` (a raw, not-yet-linked debit)
        belong to `commitment`'s series, or does it look like a novel
        recurrence forming? Returns `None` when the model finds neither.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape.
        """
        prompt = load_prompt("A28")
        rendered = prompt.text.format(
            event_counterparty=event.counterparty_raw,
            event_amount=f"{event.amount:.2f}",
            event_currency=event.currency,
            event_occurred_at=event.occurred_at.isoformat(),
            commitment_label=commitment.label,
            commitment_counterparty=commitment.counterparty,
            commitment_amount=f"{commitment.amount:.2f}",
            commitment_cadence=commitment.cadence,
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        matches = require_bool(parsed, "matches", agent_id=AGENT_ID, default=False)
        looks_new_recurrence = require_bool(
            parsed, "looks_like_new_recurrence", agent_id=AGENT_ID, default=False
        )
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)

        if matches:
            return ReconciliationFinding(
                kind="recurrence_detected",
                commitment_id=commitment.id,
                subject_event_ids=(event.id,),
                explanation=reasoning,
                evidence={"counterparty_raw": event.counterparty_raw, "matched_to": commitment.label},
                confidence=confidence,
                requires_dispute_branch=False,
            )
        if looks_new_recurrence:
            return ReconciliationFinding(
                kind="recurrence_detected",
                commitment_id=None,
                subject_event_ids=(event.id,),
                explanation=reasoning,
                evidence={
                    "counterparty_raw": event.counterparty_raw,
                    "note": "no existing commitment matched; recurrence signal only",
                },
                confidence=confidence,
                requires_dispute_branch=False,
            )
        return None

    def check_sms_ledger_mismatch(
        self, *, sms_event: LedgerEvent, ledger_event: LedgerEvent
    ) -> ReconciliationFinding | None:
        """Deterministic. Returns `None` when the two figures agree —
        nothing to route to the dispute branch."""
        return _compare_figures(
            kind="sms_ledger_mismatch",
            reconciled_kind=None,
            amount_a=sms_event.amount,
            amount_b=ledger_event.amount,
            currency_a=sms_event.currency,
            currency_b=ledger_event.currency,
            commitment_id=None,
            subject_event_ids=(sms_event.id, ledger_event.id),
            explanation_subject="SMS vs ledger",
            label_a="sms",
            label_b="ledger",
        )

    def check_salary_payment(
        self, *, recorded_event: LedgerEvent, computed_net_salary_due: float, computed_currency: str
    ) -> ReconciliationFinding:
        """Deterministic cross-check that a recorded `LedgerEvent(kind=
        SALARY)` matches what A34/`salary_calculator.calculate_salary`
        actually computed as due. **Never computes the figure itself** —
        `computed_net_salary_due` is always the caller's (A34's) already-
        computed result.

        Raises:
            ValueError: `recorded_event.kind is not LedgerEventKind.SALARY`.
            errors.CurrencyMismatch: currencies disagree.
        """
        if recorded_event.kind is not LedgerEventKind.SALARY:
            raise ValueError(f"recorded_event must be LedgerEventKind.SALARY, got {recorded_event.kind!r}")
        finding = _compare_figures(
            kind="salary_mismatch",
            reconciled_kind="salary_reconciled",
            amount_a=recorded_event.amount,
            amount_b=computed_net_salary_due,
            currency_a=recorded_event.currency,
            currency_b=computed_currency,
            commitment_id=None,
            subject_event_ids=(recorded_event.id,),
            explanation_subject="recorded salary payment vs computed salary due",
            label_a="recorded",
            label_b="computed",
        )
        assert (
            finding is not None
        )  # reconciled_kind is always set, so _compare_figures never returns None here
        return finding

    def reconcile(self, request: ReconciliationRequest) -> ReconciliationRunResult:
        """Runs every applicable check for one `ReconciliationRequest` and
        assembles the findings. Cost discipline: the Pro-tier matching
        pass only runs when `request.unmatched_events` is non-empty."""
        findings: list[ReconciliationFinding] = []
        model_tier: Literal["pro", "deterministic"] = "deterministic"
        prompt_version: str | None = None

        events = (
            request.series_events
            if request.series_events is not None
            else self.fetch_series(request.commitment.id)
        )

        price_change = _detect_price_change(request.commitment)
        if price_change is not None:
            findings.append(price_change)

        findings.extend(_detect_duplicates(commitment_id=request.commitment.id, events=events))

        for unmatched in request.unmatched_events:
            match_finding = self.match_unlinked_event(event=unmatched, commitment=request.commitment)
            model_tier = "pro"
            prompt_version = load_prompt("A28").version
            if match_finding is not None:
                findings.append(match_finding)

        if request.sms_reported_event is not None and request.ledger_recorded_event is not None:
            mismatch = self.check_sms_ledger_mismatch(
                sms_event=request.sms_reported_event, ledger_event=request.ledger_recorded_event
            )
            if mismatch is not None:
                findings.append(mismatch)

        if request.recorded_salary_event is not None and request.computed_salary is not None:
            computed = request.computed_salary
            if not isinstance(computed, SalaryCalculationResult):
                raise TypeError(
                    f"ReconciliationRequest.computed_salary must be a SalaryCalculationResult, "
                    f"got {type(computed).__name__}"
                )
            findings.append(
                self.check_salary_payment(
                    recorded_event=request.recorded_salary_event,
                    computed_net_salary_due=computed.net_salary_due,
                    computed_currency=computed.currency,
                )
            )

        logger.info(
            "agents.ledger.a28.completed",
            commitment_id=str(request.commitment.id),
            finding_count=len(findings),
            model_tier=model_tier,
        )
        return ReconciliationRunResult(
            findings=tuple(findings),
            model_tier=model_tier,
            prompt_version=prompt_version,
            invocation_id=uuid.uuid4().hex,
        )


__all__ = ["AGENT_ID", "ReconciliationAgent"]
