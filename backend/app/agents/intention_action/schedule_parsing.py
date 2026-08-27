"""Real, deterministic parsing of `SCHEDULE`-kind `Constraint.structured`
against ADR-015's formal key schema, plus the deterministic candidate-
window overlap check A25 (Window Scheduling) runs against a person's real
schedule constraints. No Gemini call anywhere in this module — parsing a
structured dict of three known keys and checking two time ranges for
overlap is arithmetic, not reasoning (mirrors `app.agents.ledger.
staff_payroll_agent`'s "arithmetic deterministic" precedent, and
`app.solvers.*`'s existing deterministic-solver pattern generally).

## ADR-015's formal `SCHEDULE` `structured` schema

- `days_of_week`: comma-separated lowercase 3-letter days
  (`"mon,tue,wed,thu,fri"`), or the literal `"daily"` for all seven.
- `start_time` / `end_time`: `"HH:MM"`, 24-hour, local time.

## Never crash on a malformed or legacy entry

A `SCHEDULE`-kind `Constraint` that predates ADR-015's formal schema (or
was written with a typo, an out-of-range hour, an unrecognised day
abbreviation) is real data this module must not crash on — `parse_
schedule_constraint` returns `None` for anything it cannot confidently
parse, and every caller in this package degrades to `AvailabilityVerdict.
CANNOT_DETERMINE` for that specific constraint rather than guessing
either "available" or "blocked."
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time

from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId

from .types import AvailabilityVerdict

_VALID_DAY_ABBREVIATIONS: frozenset[str] = frozenset({"mon", "tue", "wed", "thu", "fri", "sat", "sun"})
_ALL_DAYS: frozenset[str] = _VALID_DAY_ABBREVIATIONS
_PYTHON_WEEKDAY_TO_ABBREVIATION: tuple[str, ...] = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
"""`datetime.weekday()` returns `0` for Monday .. `6` for Sunday — this
tuple is index-aligned to that, not to `_VALID_DAY_ABBREVIATIONS`'s
(arbitrary, alphabetical-by-set) iteration order."""


@dataclass(frozen=True, slots=True)
class ParsedScheduleWindow:
    """One successfully-parsed `SCHEDULE`-kind constraint, ready for the
    real overlap check — never constructed for a constraint this module
    could not confidently parse (see `parse_schedule_constraint`)."""

    constraint_id: NodeId
    severity: ConstraintSeverity
    days_of_week: frozenset[str]
    """Lowercase 3-letter day abbreviations this window applies to —
    always a non-empty subset of `_VALID_DAY_ABBREVIATIONS`."""
    start_time: time
    end_time: time


def _parse_time(raw: str) -> time | None:
    parts = raw.strip().split(":")
    if len(parts) != 2:
        return None
    hour_str, minute_str = parts
    if not (hour_str.isdigit() and minute_str.isdigit()):
        return None
    hour, minute = int(hour_str), int(minute_str)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return time(hour=hour, minute=minute)


def _parse_days_of_week(raw: str) -> frozenset[str] | None:
    normalized = raw.strip().lower()
    if normalized == "daily":
        return _ALL_DAYS
    if not normalized:
        return None
    days = frozenset(day.strip() for day in normalized.split(","))
    if not days or not days.issubset(_VALID_DAY_ABBREVIATIONS):
        return None
    return days


def parse_schedule_constraint(constraint: Constraint) -> ParsedScheduleWindow | None:
    """Parses one `Constraint` against ADR-015's formal `SCHEDULE` schema.

    Args:
        constraint: any `Constraint` node — non-`SCHEDULE`-kind
            constraints always return `None` (this function is safe to
            call over an unfiltered constraint list).

    Returns:
        A `ParsedScheduleWindow`, or `None` when `constraint.kind` is not
        `ConstraintKind.SCHEDULE`, or `constraint.structured` is missing
        any of `days_of_week`/`start_time`/`end_time`, or any of those
        values does not match ADR-015's formal format (a legacy informal
        entry, e.g. the pre-migration `{"quiet_hours": "14:00-16:00"}`
        shape, included). Never raises — a malformed real-world entry is
        exactly the expected case this function exists to degrade
        gracefully on, not a bug to surface as an exception.
    """
    if constraint.kind is not ConstraintKind.SCHEDULE:
        return None

    days_raw = constraint.structured.get("days_of_week")
    start_raw = constraint.structured.get("start_time")
    end_raw = constraint.structured.get("end_time")
    if days_raw is None or start_raw is None or end_raw is None:
        return None

    days = _parse_days_of_week(days_raw)
    start = _parse_time(start_raw)
    end = _parse_time(end_raw)
    if days is None or start is None or end is None:
        return None
    if start >= end:
        # An overnight/zero-length window is not representable under
        # ADR-015's schema as written (no "crosses midnight" convention
        # was defined) — treated as unparseable rather than guessed at.
        return None

    return ParsedScheduleWindow(
        constraint_id=constraint.id,
        severity=constraint.severity,
        days_of_week=days,
        start_time=start,
        end_time=end,
    )


def _windows_overlap(window: ParsedScheduleWindow, candidate: tuple[datetime, datetime]) -> bool:
    candidate_start, candidate_end = candidate
    if candidate_start.date() != candidate_end.date():
        # A candidate window spanning midnight is checked day-by-day is
        # out of scope for this simple, real overlap check — conservatively
        # treated as *not* overlapping a same-day schedule window rather
        # than guessed at either way; a caller offering a multi-day
        # candidate window should split it into same-day candidates first.
        return False
    day_abbreviation = _PYTHON_WEEKDAY_TO_ABBREVIATION[candidate_start.weekday()]
    if day_abbreviation not in window.days_of_week:
        return False
    return candidate_start.time() < window.end_time and candidate_end.time() > window.start_time


def person_availability_for_window(
    schedule_constraints: tuple[Constraint, ...], candidate: tuple[datetime, datetime]
) -> AvailabilityVerdict:
    """The real, deterministic ADR-015 availability check for one person
    against one candidate window.

    Args:
        schedule_constraints: every `Constraint` `CONSTRAINS`-linked to
            this person (unfiltered by kind is fine — non-`SCHEDULE`
            constraints are ignored).
        candidate: the `(start, end)` window being evaluated.

    Returns:
        `AvailabilityVerdict.HARD_BLOCKED` if any parseable `HARD`
        schedule constraint overlaps `candidate`; else `SOFT_AVOID` if any
        parseable `SOFT` one overlaps; else `AVAILABLE` if either at least
        one `SCHEDULE`-kind constraint parsed cleanly and none overlapped,
        or this person has no `SCHEDULE`-kind constraint on file at all
        (no evidence of a block is treated as available, not as unknown —
        the household graph is an open-world record of known constraints,
        not an exhaustive schedule); else `CANNOT_DETERMINE` only when
        this person has at least one real `SCHEDULE`-kind constraint but
        every single one of them was unparseable (a malformed or legacy
        entry genuinely could be blocking — never silently ignored).
    """
    parsed_windows = [
        window
        for constraint in schedule_constraints
        if (window := parse_schedule_constraint(constraint)) is not None
    ]
    schedule_kind_count = sum(1 for c in schedule_constraints if c.kind is ConstraintKind.SCHEDULE)

    if not parsed_windows:
        if schedule_kind_count > 0:
            return AvailabilityVerdict.CANNOT_DETERMINE
        return AvailabilityVerdict.AVAILABLE

    hard_blocked = False
    soft_avoid = False
    for window in parsed_windows:
        if not _windows_overlap(window, candidate):
            continue
        if window.severity is ConstraintSeverity.HARD:
            hard_blocked = True
        else:
            soft_avoid = True

    if hard_blocked:
        return AvailabilityVerdict.HARD_BLOCKED
    if soft_avoid:
        return AvailabilityVerdict.SOFT_AVOID
    return AvailabilityVerdict.AVAILABLE


__all__ = ["ParsedScheduleWindow", "parse_schedule_constraint", "person_availability_for_window"]
