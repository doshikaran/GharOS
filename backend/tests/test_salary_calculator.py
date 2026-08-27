"""Tests for `app.solvers.salary_calculator.calculate_salary` (PHASES.md
Phase 7, spec §16.2 "days − absences − advances").

Pure unit tests, no Firestore emulator involved — `calculate_salary` does
no graph I/O (see the module's own docstring), so every scenario here is
constructed from plain `AttendanceRecord`/`LedgerEvent` instances, matching
the E1 charter's "fully unit-testable with no mocking needed beyond plain
data" requirement.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from contracts.graph_types import AttendanceRecord, LedgerEvent, LedgerEventKind, NodeId

from app.solvers.salary_calculator import SalaryCalculationResult, calculate_salary
from tests.conftest import NOW, make_provenance

_STAFF_ID = NodeId("person-maya")
_DAILY_RATE = 500.0


def _attendance(
    *,
    days_present: int = 26,
    days_absent: int = 2,
    days_on_leave: int = 2,
    total_days_in_period: int = 30,
    daily_marks: dict[str, str] | None = None,
    advance_notations: tuple[str, ...] = (),
) -> AttendanceRecord:
    return AttendanceRecord(
        id=NodeId("attendance-maya-2026-08"),
        provenance=make_provenance(),
        staff_person_id=_STAFF_ID,
        month="2026-08",
        days_present=days_present,
        days_absent=days_absent,
        days_on_leave=days_on_leave,
        total_days_in_period=total_days_in_period,
        daily_marks=daily_marks or {},
        advance_notations=advance_notations,
    )


def _advance(node_id: str, amount: float, *, currency: str = "INR") -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(node_id),
        provenance=make_provenance(),
        kind=LedgerEventKind.ADVANCE,
        amount=amount,
        currency=currency,
        occurred_at=NOW - timedelta(days=5),
        counterparty_raw="MAYA BAI",
    )


class TestCleanMonth:
    def test_no_absences_no_leave_no_advances(self) -> None:
        attendance = _attendance(days_present=30, days_absent=0, days_on_leave=0, total_days_in_period=30)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE)
        assert result.days_worked == 30
        assert result.gross_amount == 15_000.0
        assert result.total_advances_deducted == 0.0
        assert result.net_salary_due == 15_000.0
        assert result.floored_at_zero is False
        assert result.advance_event_ids == ()
        assert result.currency == "INR"
        assert result.staff_person_id == _STAFF_ID
        assert result.month == "2026-08"
        assert isinstance(result, SalaryCalculationResult)


class TestAbsences:
    def test_absences_reduce_days_worked_but_not_double_counted(self) -> None:
        attendance = _attendance(days_present=24, days_absent=6, days_on_leave=0, total_days_in_period=30)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE)
        assert result.days_worked == 24
        assert result.days_absent == 6
        assert result.gross_amount == 12_000.0
        assert result.net_salary_due == 12_000.0


class TestLeave:
    def test_leave_is_unpaid_by_default_and_excluded_from_days_worked(self) -> None:
        """Policy call #1 (documented in the module): all `"leave"` marks
        are unpaid by default — `days_on_leave` never contributes to
        `days_worked` or `gross_amount`, only to the audit-visible
        `days_on_leave_unpaid` field."""
        attendance = _attendance(days_present=25, days_absent=0, days_on_leave=5, total_days_in_period=30)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE)
        assert result.days_worked == 25
        assert result.days_on_leave_unpaid == 5
        assert result.gross_amount == 25 * _DAILY_RATE


class TestSingleAdvance:
    def test_advance_deducted_from_gross(self) -> None:
        attendance = _attendance(days_present=26, days_absent=2, days_on_leave=2, total_days_in_period=30)
        advance = _advance("ledger-advance-1", 2_000.0)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=[advance])
        assert result.gross_amount == 13_000.0
        assert result.total_advances_deducted == 2_000.0
        assert result.net_salary_due == 11_000.0
        assert result.advance_event_ids == (NodeId("ledger-advance-1"),)
        assert result.floored_at_zero is False

    def test_advance_amount_never_read_from_advance_notations(self) -> None:
        """ADR-013: `advance_notations` is cross-reference-only text. This
        test proves it plays no role in the arithmetic — a wildly
        different notation text does not change the computed deduction,
        only the real `LedgerEvent` amount does."""
        attendance = _attendance(
            days_present=26,
            days_absent=2,
            days_on_leave=2,
            total_days_in_period=30,
            advance_notations=("₹50,000 advance!! (a decoy figure never used by the calculator)",),
        )
        advance = _advance("ledger-advance-1", 2_000.0)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=[advance])
        assert result.total_advances_deducted == 2_000.0


class TestMultipleAdvances:
    def test_multiple_advances_sum(self) -> None:
        attendance = _attendance(days_present=28, days_absent=0, days_on_leave=2, total_days_in_period=30)
        advances = [
            _advance("ledger-advance-1", 1_000.0),
            _advance("ledger-advance-2", 1_500.0),
            _advance("ledger-advance-3", 500.0),
        ]
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=advances)
        assert result.total_advances_deducted == 3_000.0
        assert result.gross_amount == 14_000.0
        assert result.net_salary_due == 11_000.0
        assert result.advance_event_ids == (
            NodeId("ledger-advance-1"),
            NodeId("ledger-advance-2"),
            NodeId("ledger-advance-3"),
        )


class TestEdgeCases:
    def test_zero_days_present_yields_zero_gross_and_zero_net(self) -> None:
        attendance = _attendance(days_present=0, days_absent=30, days_on_leave=0, total_days_in_period=30)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE)
        assert result.days_worked == 0
        assert result.gross_amount == 0.0
        assert result.net_salary_due == 0.0
        assert result.floored_at_zero is False

    def test_advances_exceeding_gross_floor_at_zero_not_negative(self) -> None:
        """Policy call #2 (documented in the module): `net_salary_due`
        floors at zero rather than going negative."""
        attendance = _attendance(days_present=5, days_absent=0, days_on_leave=0, total_days_in_period=30)
        advance = _advance("ledger-advance-1", 10_000.0)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=[advance])
        assert result.gross_amount == 2_500.0
        assert result.total_advances_deducted == 10_000.0
        assert result.net_salary_due == 0.0
        assert result.floored_at_zero is True

    def test_advances_exactly_equal_to_gross_is_not_flagged_as_floored(self) -> None:
        attendance = _attendance(days_present=4, days_absent=0, days_on_leave=0, total_days_in_period=30)
        advance = _advance("ledger-advance-1", 4 * _DAILY_RATE)
        result = calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=[advance])
        assert result.net_salary_due == 0.0
        assert result.floored_at_zero is False


class TestValidation:
    def test_negative_daily_rate_rejected(self) -> None:
        attendance = _attendance()
        with pytest.raises(ValueError, match="daily_rate"):
            calculate_salary(attendance, daily_rate=-1.0)

    def test_negative_days_present_rejected(self) -> None:
        attendance = _attendance(days_present=-1)
        with pytest.raises(ValueError, match="days_present"):
            calculate_salary(attendance, daily_rate=_DAILY_RATE)

    def test_negative_days_absent_rejected(self) -> None:
        attendance = _attendance(days_absent=-1)
        with pytest.raises(ValueError, match="days_absent"):
            calculate_salary(attendance, daily_rate=_DAILY_RATE)

    def test_negative_days_on_leave_rejected(self) -> None:
        attendance = _attendance(days_on_leave=-1)
        with pytest.raises(ValueError, match="days_on_leave"):
            calculate_salary(attendance, daily_rate=_DAILY_RATE)

    def test_non_advance_ledger_event_kind_rejected(self) -> None:
        """Structural enforcement of ADR-013's rule: only real ADVANCE
        LedgerEvents may be handed in as advances — a caller mistake
        (e.g. passing a DEBIT) must be rejected, not silently summed."""
        attendance = _attendance()
        not_an_advance = LedgerEvent(
            id=NodeId("ledger-debit-1"),
            provenance=make_provenance(),
            kind=LedgerEventKind.DEBIT,
            amount=500.0,
            currency="INR",
            occurred_at=NOW,
            counterparty_raw="FRESHMART",
        )
        with pytest.raises(ValueError, match="ADVANCE"):
            calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=[not_an_advance])

    def test_mismatched_currency_rejected(self) -> None:
        attendance = _attendance()
        advance = _advance("ledger-advance-1", 1_000.0, currency="USD")
        with pytest.raises(ValueError, match="currency"):
            calculate_salary(attendance, daily_rate=_DAILY_RATE, advance_events=[advance])
