"""Shared, non-agent-specific dataclasses for the Household Ledger (A27-A34,
spec §10, PHASES.md Phase 7). Not itself an agent — these are the shapes
that flow between A28 (Reconciliation) -> A29 (Leakage) -> A30 (Recovery
Drafting), and separately A28 -> A32 (Dispute Branch), and A34 (Staff
Payroll) end to end.

Kept separate from any one agent module so `reconciliation_agent.py`,
`leakage_detection_agent.py`, `recovery_drafting_agent.py`,
`dispute_branch_agent.py`, and `staff_payroll_agent.py` all import the same
finding/draft shapes rather than each defining a slightly different one —
mirrors `app.agents.consequence.types`'s established role for A12-A16.

**Every result type here is deliberately narrow about what it can express.**
`DisputePresentation` is the sharpest example: it has no field that could
ever hold a single "correct" figure, because A32's forbidden behaviour
("choosing which is correct" — spec §15.7 A32) must be structurally
impossible to represent, not merely untested.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from contracts.graph_types import AttendanceRecord, LedgerEvent, NodeId, Person, RecurringCommitment

# ---------------------------------------------------------------------------
# A28 — Reconciliation Agent output shapes
# ---------------------------------------------------------------------------

ReconciliationFindingKind = Literal[
    "duplicate",
    "price_change",
    "recurrence_detected",
    "sms_ledger_mismatch",
    "dues_mismatch",
    "salary_reconciled",
    "salary_mismatch",
]
"""Every shape of thing A28 can report (spec §10.3B: "match debits to
series; detect novel recurrences; detect price changes; detect duplicates;
reconcile dues; compute [cross-check] staff salary; flag SMS-vs-ledger
mismatches"). `"salary_reconciled"` is the clean-match case — recorded
just as auditably as a mismatch, never silently skipped, so a household
can see A28 actually checked."""


@dataclass(frozen=True, slots=True)
class ReconciliationFinding:
    """One thing A28 detected — never a resolution, never a fix. A28 is
    read-only by construction (spec §10.5); this type has no field that
    could express an action taken."""

    kind: ReconciliationFindingKind
    commitment_id: NodeId | None
    """The RECURRING_COMMITMENT this finding concerns, if any (absent for
    e.g. a standalone dues mismatch with no known series)."""
    subject_event_ids: tuple[NodeId, ...]
    """The real LEDGER_EVENT node ids this finding is evidenced by — the
    audit trail, never a summary that discards which events were looked
    at."""
    explanation: str
    evidence: dict[str, str]
    """Human-readable evidence key/value pairs (e.g. `{"old_price": "2300.00",
    "new_price": "2500.00", "change_pct": "8.7%"}`) — what a household
    member or the payroll/ledger review UI would want to see alongside the
    verdict."""
    confidence: float
    requires_dispute_branch: bool
    """True only for `"sms_ledger_mismatch"` / `"dues_mismatch"` /
    `"salary_mismatch"` findings that name two independently-sourced,
    disagreeing figures — the caller routes these to A32, never auto-
    resolves them itself (spec §10.3B failure mode: "mismatch -> dispute
    branch")."""


@dataclass(frozen=True, slots=True)
class ReconciliationRequest:
    """A28's input for one reconciliation pass over one
    RECURRING_COMMITMENT, plus whatever adjacent cross-checks apply this
    run — every field beyond `commitment` is optional so a caller only
    supplies what it actually has evidence for."""

    commitment: RecurringCommitment
    series_events: tuple[LedgerEvent, ...] | None = None
    """Pre-resolved LEDGER_EVENTs belonging to `commitment`'s series. When
    `None`, `ReconciliationAgent.reconcile` fetches them itself via its
    T0-only tool registry (`series` operation) — never a raw `GraphReader`
    reference held directly (spec §10.5: read tools only)."""
    unmatched_events: tuple[LedgerEvent, ...] = ()
    """Raw debits not yet linked to any known series — candidates for
    A28's Pro-tier "does this belong to this commitment" matching pass."""
    sms_reported_event: LedgerEvent | None = None
    ledger_recorded_event: LedgerEvent | None = None
    """The independently-sourced pair to check for an SMS-vs-ledger
    mismatch — both describe the same real-world transaction from two
    different channels. Either both are given or neither is."""
    recorded_salary_event: LedgerEvent | None = None
    computed_salary: object | None = None
    """`app.solvers.salary_calculator.SalaryCalculationResult | None` —
    typed as `object` for the same reason as `PayrollResult.salary` above.
    Either both `recorded_salary_event` and `computed_salary` are given,
    or neither is."""


@dataclass(frozen=True, slots=True)
class ReconciliationRunResult:
    """The complete output of one `ReconciliationAgent.reconcile()` call."""

    findings: tuple[ReconciliationFinding, ...]
    model_tier: Literal["pro", "deterministic"]
    """`"deterministic"` when every finding this run produced came from the
    pure arithmetic layer (duplicate/price-change/mismatch detection) with
    no Gemini call made at all — cost discipline: A28 never calls the
    model just to confirm nothing needs matching judgment."""
    prompt_version: str | None
    """`None` when `model_tier == "deterministic"` (no prompt was loaded)."""
    invocation_id: str


# ---------------------------------------------------------------------------
# A29 — Leakage Detection output shapes
# ---------------------------------------------------------------------------

LeakageVerdict = Literal["leakage", "worth_keeping", "ambiguous"]


@dataclass(frozen=True, slots=True)
class LeakageAssessmentRequest:
    """A29's input: one RECURRING_COMMITMENT plus the household-priorities
    context to reason it against — mirrors
    `app.agents.consequence.types.ImplicationRequest`'s "pre-resolved
    context, assembled by the caller" shape."""

    commitment_id: NodeId
    label: str
    counterparty: str
    amount: float
    cadence: str
    price_history: tuple[tuple[datetime, float], ...]
    last_used_at: datetime | None
    status: Literal["active", "paused", "cancelled"]
    household_priorities: str
    """Free-text household-priorities context this specific commitment
    should be judged against (e.g. "cutting non-essential spend this
    quarter"; "gym membership was a New Year resolution, rarely mentioned
    since"). No existing graph node type models "current household
    priorities" as structured data (out of this phase's contract scope) —
    callers supply real, current context directly, the same documented
    scope decision `app.agents.consequence.context`'s module docstring
    makes for PERSON availability."""
    now: datetime
    """Reference "today" for computing days-since-last-used — injected
    rather than read from the system clock, so this module stays a pure
    function of its arguments and is deterministically testable."""


@dataclass(frozen=True, slots=True)
class LeakageFinding:
    """A29's verdict on one commitment — the "worth reasoning" step (spec
    §10.3C). Never a cancellation; A29 holds no write/communication/
    payment tool at all (spec §15.7 A29 forbidden list) — this type is the
    entirety of what it can produce."""

    commitment_id: NodeId
    verdict: LeakageVerdict
    reasoning: str
    """A real, per-item reasoned judgment against this commitment's actual
    usage signal and the household's stated priorities — never a bare
    rule like "unused for 60 days" (spec §15.7 A29: "usage-aware judgment,
    not rules")."""
    days_since_last_used: int | None
    """`None` only when `last_used_at` was never recorded at all."""
    price_change_pct: float | None
    """Percentage change from the oldest to the newest `price_history`
    entry, `None` when fewer than two entries exist."""
    confidence: float
    evidence: dict[str, str]


# ---------------------------------------------------------------------------
# A30 — Recovery Drafting output shapes
# ---------------------------------------------------------------------------

RecoveryDesiredOutcome = Literal["cancel", "price_adjustment_request", "dispute_charge", "refund_claim"]
RecoveryDraftKind = Literal["cancellation", "price_adjustment_request", "dispute_filing", "refund_claim"]


@dataclass(frozen=True, slots=True)
class RecoveryDraftRequest:
    """A30's input: an A29 `LeakageFinding` or an A28 `ReconciliationFinding`
    naming a price/billing issue, reduced by the caller to what A30 needs
    to draft against — this module never re-derives the underlying
    judgment itself, only turns an already-made finding into a real draft."""

    finding_kind: Literal["leakage", "price_change", "billing_error", "duplicate"]
    vendor_name: str
    issue_summary: str
    """Human-readable summary of what's being drafted against — the
    `LeakageFinding.reasoning`, or the `ReconciliationFinding.explanation`
    plus its `evidence`, assembled by the caller."""
    desired_outcome: RecoveryDesiredOutcome
    merchant_playbook: str | None = None
    """A learned per-merchant playbook (spec §15.7 A30: "using learned
    per-merchant playbooks") — a known pattern for how this vendor's
    cancellation/dispute flow actually works (e.g. "requires a written
    30-day notice by email, not the app's in-app cancel button"), if the
    household has one on file. `None` falls back to a generic playbook —
    no per-merchant learning store exists yet this phase (E3/A33's
    territory); a real one is a natural Phase-14-consolidation follow-on,
    noted in this phase's final report rather than stubbed here."""


@dataclass(frozen=True, slots=True)
class RecoveryDraft:
    """A30's entire output — draft only, never dispatched. Sending is
    Phase 10's Outbound Concierge job, structurally out of this type's
    reach: there is no `sent_at` field, no send-status, nothing that could
    represent this draft having left the household (spec §15.7 A30
    forbidden list: "sending; moving money")."""

    target_vendor: str
    ask: str
    """One-sentence statement of what's being requested (e.g. "cancel the
    membership effective immediately" / "roll the price back to ₹2,300 or
    match the original quote" / "refund the duplicate ₹850 charge")."""
    message_text: str
    """The full drafted message/claim text — never sent by this agent or
    any other in this package."""
    draft_kind: RecoveryDraftKind
    confidence: float
    reasoning: str


# ---------------------------------------------------------------------------
# A32 — Dispute Branch output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ConflictingFigure:
    """One of the two independently-sourced figures A32 presents side by
    side. Neither this type nor `DisputePresentation` below ever carries a
    verdict about which figure is right."""

    source_label: str
    """Which channel this figure comes from, e.g. `"SMS notification"`,
    `"ledger record"`, `"attendance register"`, `"recorded SALARY
    payment"`."""
    amount: float
    currency: str
    reported_at: datetime
    evidence_event_id: NodeId
    """The real LEDGER_EVENT (or equivalent) node id backing this figure —
    always resolvable, never a bare number with no provenance."""
    evidence_text: str
    """The raw text/evidence backing this figure — e.g. the LEDGER_EVENT's
    `counterparty_raw`, or a quoted SMS/register excerpt."""


@dataclass(frozen=True, slots=True)
class DisputePresentation:
    """A32's entire output. **Deliberately has no field that could hold a
    single chosen/resolved figure** — spec §15.7 A32 forbidden list:
    "choosing which is correct." `discrepancy_amount` is a neutral,
    derived arithmetic fact (`abs(figure_a.amount - figure_b.amount)`),
    not a resolution; `escalated_to` is pinned to the one value this
    module can ever produce. There is structurally no way to add a
    "the real figure was X" claim to an instance of this type without
    editing this frozen dataclass's own field list — which is exactly the
    point (`backend/tests/test_dispute_branch.py`'s adversarial proof
    checks this directly against `__dataclass_fields__`, not just by
    convention)."""

    subject: str
    """What's in dispute, e.g. `"August society maintenance debit"` or
    `"Maya's August salary payment"`."""
    figure_a: ConflictingFigure
    figure_b: ConflictingFigure
    discrepancy_amount: float
    context: str
    """Neutral narrative context a human needs to resolve this — written
    to never favour either figure (enforced by A32's prompt and reviewed
    at Gate 7; not narrated as evidence for one side)."""
    confidence: float
    escalated_to: Literal["human_resolution"] = "human_resolution"


# ---------------------------------------------------------------------------
# A34 — Staff Payroll output shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PayrollRequest:
    """A34's input: one staff member's real `AttendanceRecord` for one
    month, plus the real `ADVANCE`-kind `LedgerEvent`s already resolved
    for that person and period (never re-derived from
    `AttendanceRecord.advance_notations` — ADR-013), plus this household's
    configured pay terms for this staff member. `daily_rate` and
    `salary_due_by` have no natural home on any frozen contract type
    (mirrors `app.solvers.salary_calculator.calculate_salary`'s own
    `daily_rate` parameter docstring rationale exactly) — callers supply
    them directly from household-configured pay terms."""

    staff_person: Person
    attendance: AttendanceRecord
    advance_events: tuple[LedgerEvent, ...]
    daily_rate: float
    salary_due_by: datetime
    currency: str = "INR"
    confidence_floor: float = 0.75
    """Below this, `attendance.provenance.confidence` is not trusted on its
    own — see `staff_payroll_agent.py`'s module docstring for the full
    decision flow."""


@dataclass(frozen=True, slots=True)
class UnresolvedMark:
    """One day A34 could not confidently interpret, even after its own
    Pro-tier attempt — the register image must be shown to a human for
    this day, never silently guessed (spec §10.6: "misread handwriting ->
    confidence threshold; below it, show the image to the human")."""

    day: str
    """`"01"`-`"31"`, matching `AttendanceRecord.daily_marks` keys."""
    reason: str


@dataclass(frozen=True, slots=True)
class PayrollResult:
    """A34's entire output — the `SalaryCalculationResult` (E1's
    deterministic solver, never re-derived here) plus which marks, if any,
    needed human review, plus the register image reference the payroll
    review UI (E4) shows beside the computed figure."""

    staff_person_id: NodeId
    month: str
    salary: object | None
    """`app.solvers.salary_calculator.SalaryCalculationResult | None` —
    typed as `object` here rather than importing the solver's concrete
    type into this shared shapes module, to keep
    `backend/app/agents/ledger/types.py` free of a cross-package import
    that only `staff_payroll_agent.py` actually needs; that module
    re-exports the precise type. `None` only when `needs_human_review` is
    `True` — never a guessed figure sitting alongside an unresolved mark."""
    needs_human_review: bool
    unresolved_marks: tuple[UnresolvedMark, ...]
    review_reason: str | None
    """Populated whenever `needs_human_review` is `True` — the single,
    human-readable reason (record-level low confidence, an unresolved
    mark, or both)."""
    register_image_ref: str | None
    """The original register's `SourceDocument` id (from
    `AttendanceRecord.provenance.source_ref.source_document_id`), for the
    payroll review UI to render beside the computed figure — populated
    whenever the record's provenance carries one, regardless of whether
    review is needed, so the UI can always show the source."""
    obligation_node_id: NodeId | None
    """The written "Pay {name}'s salary" OBLIGATION's id — `None` when no
    salary was computed (nothing determinate to schedule yet)."""
    confidence: float
    reasoning: str
    model_tier: Literal["pro", "deterministic"]
    """`"deterministic"` when the attendance record was clean (no ambiguous
    marks, confidence above floor) — no Gemini call made at all."""


__all__ = [
    "ConflictingFigure",
    "DisputePresentation",
    "LeakageAssessmentRequest",
    "LeakageFinding",
    "LeakageVerdict",
    "PayrollRequest",
    "PayrollResult",
    "ReconciliationFinding",
    "ReconciliationFindingKind",
    "ReconciliationRequest",
    "ReconciliationRunResult",
    "RecoveryDesiredOutcome",
    "RecoveryDraft",
    "RecoveryDraftKind",
    "RecoveryDraftRequest",
    "UnresolvedMark",
]
