"""Deterministic obligation staleness rule — the single canonical home of
the rule, shared by every consumer that needs it.

**Provenance of this rule:** it originated as Phase 9's A22 Intention
Capture agent's private `_is_stale` (with its `_STALE_AFTER_DEADLINE_DAYS`
/ `_STALE_NO_DEADLINE_DAYS` / `_TERMINAL_STATUSES` constants) — real,
deterministic, grace-period-aware business logic established there first.
ADR-021 (Phase 14) directed A11 Graph Maintainer to reuse that rule
rather than invent a second staleness definition, and left it to E1
whether to extract it to a shared importable location. E1 extracted it
here in Phase 14, into `backend/app/solvers/` — E1's owned, established
home for deterministic, no-model-call business logic
(`calibration_stats.py`, `fair_allocation.py`, `salary_calculator.py` all
live here). For part of Phase 14 the A22 agent kept a byte-for-byte
private copy of the rule (E1 could not edit the E2-owned agent file to
redirect it), so two copies briefly coexisted. DEBT-013 (Phase 15)
removed that last duplicate: `intention_capture_agent` now imports
`is_stale` from this module and its private `_is_stale` and `_STALE_*` /
`_TERMINAL_STATUSES` constants are deleted. There is now exactly one
definition of the rule, and it is this one.

**Consumers**, both via `is_stale` / `StalenessCheck`:
  - A11 Graph Maintainer — graph-wide, scheduled scope (PHASES.md
    Phase 14, ADR-021).
  - A22 Intention Capture — per-obligation scope (Phase 9 origin;
    switched to importing from here in Phase 15, DEBT-013).

Any change to the thresholds or the rule here changes behaviour for both
consumers at once — which is the point of having a single definition.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from contracts.graph_types import Obligation, ObligationStatus

_STALE_AFTER_DEADLINE_DAYS = 3
"""An `Obligation` with a real `due_at` or `must_start_by` that has passed
by at least this many days, with no status progression since (see
`is_stale`'s use of `provenance.created_at` as the last-touched signal),
is stale — a short, deliberate grace period (not zero) so a routine
same-week catch-up does not immediately count as "stale," while still
catching the pattern spec §9.1's diary-study finding names: the intention
was remembered and still didn't happen at the moment of action. This is
the canonical value of this threshold (see this module's docstring)."""

_STALE_NO_DEADLINE_DAYS = 21
"""An `Obligation` with no `due_at` and no `must_start_by` at all (an
open-ended intention, spec's own "call the dentist" worked example) is
stale once its current version has sat untouched for this many days.
This is the canonical value of this threshold (see this module's
docstring)."""

_TERMINAL_STATUSES = frozenset(
    {ObligationStatus.COMPLETED, ObligationStatus.DROPPED, ObligationStatus.SUPERSEDED}
)


@dataclass(frozen=True, slots=True)
class StalenessCheck:
    """The real, auditable result of one `is_stale` call — every field a
    caller (or a human reviewing a flagged obligation) needs to check the
    verdict, not just a bare boolean."""

    is_stale: bool
    reason: str
    """Empty string iff `is_stale` is `False`."""
    days_stale: int
    """`0` iff `is_stale` is `False`."""
    threshold_days: int
    """Which threshold (`_STALE_AFTER_DEADLINE_DAYS` or
    `_STALE_NO_DEADLINE_DAYS`) was actually applied. `0` iff `is_stale`
    is `False`."""


def is_stale(obligation: Obligation, *, now: datetime) -> StalenessCheck:
    """The real, deterministic staleness rule (see module docstring for
    provenance).

    "Last touched" is `obligation.provenance.created_at` — a graph write
    creates a new version on any real update (PHASES.md §2.2: writes
    create versions, never mutate in place), so the *current* version's
    `created_at` is a real, non-fabricated signal of when this obligation
    was last genuinely acted on, without inventing a new field.

    Args:
        obligation: the current version of one `Obligation`.
        now: the reference time to check staleness against — injected
            (never `datetime.now()` internally) so callers control it and
            tests are deterministic.

    Returns:
        A `StalenessCheck`. Terminal-status obligations (`COMPLETED`,
        `DROPPED`, `SUPERSEDED`) are never stale, by definition.
    """
    if obligation.status in _TERMINAL_STATUSES:
        return StalenessCheck(is_stale=False, reason="", days_stale=0, threshold_days=0)

    deadline = obligation.due_at or obligation.must_start_by
    if deadline is not None:
        overdue_days = (now - deadline).days
        if overdue_days >= _STALE_AFTER_DEADLINE_DAYS:
            deadline_kind = "due" if obligation.due_at is not None else "must start by"
            return StalenessCheck(
                is_stale=True,
                reason=f"{deadline_kind} {overdue_days} day(s) ago, with no status change since",
                days_stale=overdue_days,
                threshold_days=_STALE_AFTER_DEADLINE_DAYS,
            )
        return StalenessCheck(is_stale=False, reason="", days_stale=0, threshold_days=0)

    untouched_days = (now - obligation.provenance.created_at).days
    if untouched_days >= _STALE_NO_DEADLINE_DAYS:
        return StalenessCheck(
            is_stale=True,
            reason=f"no deadline set, and untouched for {untouched_days} day(s)",
            days_stale=untouched_days,
            threshold_days=_STALE_NO_DEADLINE_DAYS,
        )
    return StalenessCheck(is_stale=False, reason="", days_stale=0, threshold_days=0)


__all__ = ["StalenessCheck", "is_stale"]
