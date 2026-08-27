"""Deterministic staff salary calculator (PHASES.md Phase 7 work item —
"payroll's deterministic arithmetic tool"; spec §16.2: "Salary calculator
(days − absences − advances)"; spec §10.3/§15.9 A34 Staff Payroll Agent:
"attendance -> days worked -> minus advances -> salary due; leave and
coverage tracking").

**No LLM call anywhere in this module.** A34 (Staff Payroll, E2, Pro-tier)
is the attendance-*interpretation* agent — it reads a handwritten register,
resolves ambiguous marks, and decides low-confidence cases need a human to
see the original image. Once it has settled on a real `AttendanceRecord`
(contracts.graph_types, ADR-013), the arithmetic that turns that record
plus a pay rate plus real advances into a salary figure is pure, mechanical,
and belongs in code, never in a model call — this module is that code.

## Real advance amounts, never parsed from `advance_notations`

ADR-013 is explicit: `AttendanceRecord.advance_notations` is raw margin
text, cross-reference-only, never authoritative. The real amount of any
advance already paid this period lives on `LedgerEvent` nodes with
`kind=LedgerEventKind.ADVANCE` — this module's `advance_events` parameter
takes those nodes directly (already resolved and fetched by the caller,
e.g. A34 querying the graph for this staff member's ADVANCE events in this
period) and raises `ValueError` if any event handed in is not actually of
kind `ADVANCE`, rather than trusting the caller silently. This module does
no graph I/O itself — fetching the right `LedgerEvent`s for "this staff
member, this period" is the caller's job (a `GraphReader` query), so this
module stays a pure function over plain data, fully unit-testable with no
mocking beyond constructing `AttendanceRecord`/`LedgerEvent` instances.

## Two explicit, documented policy calls (real product decisions, not
## silently-picked defaults — see this module's final report for the
## reasoning)

1. **Paid vs. unpaid leave.** `AttendanceRecord.daily_marks` values are
   `"present" | "absent" | "leave" | "unknown"` — the contract draws no
   paid/unpaid distinction within `"leave"`. Absent a real signal to draw
   that line, this module treats **all leave as unpaid**: `days_worked`
   for pay purposes is `AttendanceRecord.days_present` only,
   `days_on_leave` is excluded. This is a real product-policy gap, not an
   invented answer — a household that grants paid leave needs a real
   signal (e.g. a `daily_marks` value distinguishing `"leave_paid"` from
   `"leave_unpaid"`, a CTO-owned contract change) before this default can
   change.
2. **Negative-salary floor.** `net_salary_due` floors at zero — advances
   exceeding gross pay for the period are never represented as a negative
   salary (a debt the staff member owes the household back). Any such
   shortfall is a real reconciliation question (does it roll to next
   month? get raised with the household?) outside this tool's scope;
   `SalaryCalculationResult.floored_at_zero` makes the case visible to the
   caller rather than silently absorbing it into a "salary due: -400"
   figure nobody asked for.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from contracts.graph_types import AttendanceRecord, LedgerEvent, LedgerEventKind, NodeId

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SalaryCalculationResult:
    """Auditable output of one salary computation — every number a human
    (or A34's payroll review UI, spec's "payroll review showing the
    register image beside the computed figure") needs to check the
    arithmetic, not just the final figure."""

    staff_person_id: NodeId
    month: str
    """Echoes `AttendanceRecord.month` (`"YYYY-MM"`)."""
    currency: str
    days_worked: int
    """`AttendanceRecord.days_present` only — see this module's docstring,
    policy call #1: unpaid leave is excluded by default."""
    days_absent: int
    days_on_leave_unpaid: int
    """`AttendanceRecord.days_on_leave`, carried through for audit
    visibility even though it does not contribute to `days_worked` under
    the current default policy."""
    daily_rate: float
    gross_amount: float
    """`days_worked * daily_rate`, before any advance deduction."""
    total_advances_deducted: float
    """Sum of `advance_events[*].amount` — sourced from real `LedgerEvent`
    nodes, never from `AttendanceRecord.advance_notations`."""
    advance_event_ids: tuple[NodeId, ...]
    """Which specific `LedgerEvent`s were deducted — the audit trail for
    `total_advances_deducted`."""
    net_salary_due: float
    """`max(0.0, gross_amount - total_advances_deducted)` — see this
    module's docstring, policy call #2."""
    floored_at_zero: bool
    """`True` when advances exceeded gross pay and `net_salary_due` was
    floored at zero rather than going negative — a real shortfall the
    caller should surface, not silently absorb."""


def calculate_salary(
    attendance: AttendanceRecord,
    *,
    daily_rate: float,
    advance_events: Sequence[LedgerEvent] = (),
    currency: str = "INR",
) -> SalaryCalculationResult:
    """Computes one staff member's salary due for one pay period.

    Formula: `days_worked = attendance.days_present` (unpaid leave and
    absences excluded — policy call #1 above) `* daily_rate`, minus the
    sum of `advance_events`' amounts, floored at zero (policy call #2
    above).

    Args:
        attendance: the settled `AttendanceRecord` for one staff member,
            one calendar month (A34's output after interpreting the
            register — this module trusts its rollup counts as
            authoritative, per ADR-013's design: `daily_marks` is kept for
            audit, not recomputed from here).
        daily_rate: this staff member's per-day pay rate, in `currency`.
            No existing graph node type has a natural "this staff member's
            salary terms" home (`RecurringCommitment` has no field linking
            it to a specific `Person`, and folding one in would be a
            contract change outside this module's scope) — callers supply
            it directly, e.g. from a household-configured rate.
        advance_events: real `LedgerEvent` nodes with
            `kind=LedgerEventKind.ADVANCE` already resolved by the caller
            for this staff member and this pay period. Every element must
            actually be of kind `ADVANCE` and share `currency`, or this
            function raises `ValueError` — never silently trusted.
        currency: the currency `daily_rate` and the result are denominated
            in. Every `advance_events` element must match, or this
            function raises `ValueError`.

    Returns:
        A `SalaryCalculationResult` carrying every intermediate figure.

    Raises:
        ValueError: `daily_rate` is negative; `attendance.days_present`,
            `days_absent`, or `days_on_leave` is negative; any element of
            `advance_events` is not of kind `LedgerEventKind.ADVANCE`; or
            any element's `currency` does not match `currency`.
    """
    if daily_rate < 0:
        raise ValueError(f"daily_rate must be >= 0, got {daily_rate!r}")
    if attendance.days_present < 0:
        raise ValueError(f"attendance.days_present must be >= 0, got {attendance.days_present!r}")
    if attendance.days_absent < 0:
        raise ValueError(f"attendance.days_absent must be >= 0, got {attendance.days_absent!r}")
    if attendance.days_on_leave < 0:
        raise ValueError(f"attendance.days_on_leave must be >= 0, got {attendance.days_on_leave!r}")

    for event in advance_events:
        if event.kind is not LedgerEventKind.ADVANCE:
            raise ValueError(
                f"advance_events must all be LedgerEventKind.ADVANCE; got {event.kind!r} for "
                f"event {event.id!r} — ADR-013: real advance amounts come only from ADVANCE "
                "LedgerEvents, never from AttendanceRecord.advance_notations or any other kind"
            )
        if event.currency != currency:
            raise ValueError(
                f"advance event {event.id!r} currency {event.currency!r} does not match "
                f"requested currency {currency!r}"
            )

    days_worked = attendance.days_present
    gross_amount = days_worked * daily_rate
    total_advances_deducted = sum(event.amount for event in advance_events)
    raw_net = gross_amount - total_advances_deducted
    net_salary_due = max(0.0, raw_net)
    floored_at_zero = raw_net < 0.0

    result = SalaryCalculationResult(
        staff_person_id=attendance.staff_person_id,
        month=attendance.month,
        currency=currency,
        days_worked=days_worked,
        days_absent=attendance.days_absent,
        days_on_leave_unpaid=attendance.days_on_leave,
        daily_rate=daily_rate,
        gross_amount=gross_amount,
        total_advances_deducted=total_advances_deducted,
        advance_event_ids=tuple(event.id for event in advance_events),
        net_salary_due=net_salary_due,
        floored_at_zero=floored_at_zero,
    )
    logger.info(
        "salary_calculator.completed",
        staff_person_id=str(attendance.staff_person_id),
        month=attendance.month,
        days_worked=days_worked,
        gross_amount=gross_amount,
        total_advances_deducted=total_advances_deducted,
        net_salary_due=net_salary_due,
        floored_at_zero=floored_at_zero,
    )
    return result


__all__ = ["SalaryCalculationResult", "calculate_salary"]
