"""Tests for `app.agents.intention_action.schedule_parsing` — ADR-015's
real, formal `SCHEDULE`-kind `Constraint.structured` schema, parsed and
checked for overlap deterministically (no Gemini call).

PHASES.md Phase 9's own acceptance list, this module's share of it:
- The real seed migration (`c2_nap_window`, `days_of_week=daily,
  start_time=14:00, end_time=16:00`, `SOFT`) parses correctly.
- Malformed/legacy/missing-key entries never crash — degrade to
  `CANNOT_DETERMINE`, never guessed either way.
- `HARD` genuinely blocks; `SOFT` is an avoid-if-possible signal only.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId

from app.agents.intention_action.schedule_parsing import (
    parse_schedule_constraint,
    person_availability_for_window,
)
from app.agents.intention_action.types import AvailabilityVerdict
from tests.conftest import make_provenance


def _schedule_constraint(
    *,
    structured: dict[str, str],
    severity: ConstraintSeverity = ConstraintSeverity.SOFT,
    node_id: str = "c-1",
) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=make_provenance(),
        kind=ConstraintKind.SCHEDULE,
        severity=severity,
        validity_start=None,
        validity_end=None,
        structured=structured,
        original_text="test schedule constraint",
    )


class TestParseScheduleConstraint:
    def test_real_migrated_nap_window_parses(self) -> None:
        """The real, live `backend/seeds/demo_household.py` entry."""
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"}
        )

        parsed = parse_schedule_constraint(constraint)

        assert parsed is not None
        assert parsed.days_of_week == frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})
        assert parsed.start_time.hour == 14
        assert parsed.end_time.hour == 16

    def test_specific_weekdays_parse(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "mon,tue,wed,thu,fri", "start_time": "09:00", "end_time": "17:00"}
        )

        parsed = parse_schedule_constraint(constraint)

        assert parsed is not None
        assert parsed.days_of_week == frozenset({"mon", "tue", "wed", "thu", "fri"})

    def test_non_schedule_kind_returns_none(self) -> None:
        constraint = Constraint(
            id=NodeId("c-dietary"),
            provenance=make_provenance(),
            kind=ConstraintKind.DIETARY,
            severity=ConstraintSeverity.HARD,
            validity_start=None,
            validity_end=None,
            structured={"allergen": "nut"},
            original_text="nut allergy",
        )

        assert parse_schedule_constraint(constraint) is None

    def test_legacy_informal_entry_never_crashes_and_returns_none(self) -> None:
        """The pre-ADR-015 informal convention this migration replaced."""
        constraint = _schedule_constraint(structured={"quiet_hours": "14:00-16:00"})

        assert parse_schedule_constraint(constraint) is None

    def test_missing_key_returns_none(self) -> None:
        constraint = _schedule_constraint(structured={"days_of_week": "daily", "start_time": "09:00"})

        assert parse_schedule_constraint(constraint) is None

    def test_malformed_time_returns_none(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "9am", "end_time": "17:00"}
        )

        assert parse_schedule_constraint(constraint) is None

    def test_out_of_range_hour_returns_none(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "25:00", "end_time": "26:00"}
        )

        assert parse_schedule_constraint(constraint) is None

    def test_unrecognised_day_abbreviation_returns_none(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "funday", "start_time": "09:00", "end_time": "10:00"}
        )

        assert parse_schedule_constraint(constraint) is None

    def test_start_after_end_returns_none(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "18:00", "end_time": "09:00"}
        )

        assert parse_schedule_constraint(constraint) is None


class TestPersonAvailabilityForWindow:
    _SATURDAY = datetime(2026, 8, 22, 15, 0, tzinfo=UTC)  # a Saturday, inside 14:00-16:00

    def test_soft_overlap_is_soft_avoid_not_hard_blocked(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"},
            severity=ConstraintSeverity.SOFT,
        )
        window = (self._SATURDAY, self._SATURDAY.replace(hour=15, minute=30))

        verdict = person_availability_for_window((constraint,), window)

        assert verdict is AvailabilityVerdict.SOFT_AVOID

    def test_hard_overlap_is_hard_blocked(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"},
            severity=ConstraintSeverity.HARD,
        )
        window = (self._SATURDAY, self._SATURDAY.replace(hour=15, minute=30))

        verdict = person_availability_for_window((constraint,), window)

        assert verdict is AvailabilityVerdict.HARD_BLOCKED

    def test_hard_blocked_wins_over_soft_overlap_on_a_different_constraint(self) -> None:
        soft = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"},
            severity=ConstraintSeverity.SOFT,
            node_id="c-soft",
        )
        hard = _schedule_constraint(
            structured={"days_of_week": "sat", "start_time": "15:00", "end_time": "15:30"},
            severity=ConstraintSeverity.HARD,
            node_id="c-hard",
        )
        window = (self._SATURDAY, self._SATURDAY.replace(hour=15, minute=15))

        verdict = person_availability_for_window((soft, hard), window)

        assert verdict is AvailabilityVerdict.HARD_BLOCKED

    def test_no_overlap_is_available(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"},
            severity=ConstraintSeverity.HARD,
        )
        morning_window = (self._SATURDAY.replace(hour=9), self._SATURDAY.replace(hour=10))

        verdict = person_availability_for_window((constraint,), morning_window)

        assert verdict is AvailabilityVerdict.AVAILABLE

    def test_wrong_day_of_week_is_available(self) -> None:
        constraint = _schedule_constraint(
            structured={"days_of_week": "mon,tue,wed,thu,fri", "start_time": "14:00", "end_time": "16:00"},
            severity=ConstraintSeverity.HARD,
        )
        # self._SATURDAY is a Saturday — outside mon-fri
        verdict = person_availability_for_window((constraint,), (self._SATURDAY, self._SATURDAY))

        assert verdict is AvailabilityVerdict.AVAILABLE

    def test_zero_schedule_constraints_is_available_not_cannot_determine(self) -> None:
        verdict = person_availability_for_window((), (self._SATURDAY, self._SATURDAY))

        assert verdict is AvailabilityVerdict.AVAILABLE

    def test_unparseable_schedule_constraint_never_crashes_and_cannot_determine(self) -> None:
        constraint = _schedule_constraint(structured={"quiet_hours": "14:00-16:00"})

        verdict = person_availability_for_window((constraint,), (self._SATURDAY, self._SATURDAY))

        assert verdict is AvailabilityVerdict.CANNOT_DETERMINE
