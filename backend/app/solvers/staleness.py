"""Deterministic obligation staleness rule — the shared, canonical home
for the rule A11 Graph Maintainer (PHASES.md Phase 14, ADR-021) reuses at
graph-wide, scheduled scope.

**Provenance of this rule, and an acknowledged, documented duplication:**
this is the exact same rule Phase 9's A22 Intention Capture agent already
established as real, deterministic, grace-period-aware business logic —
`backend/app/agents/intention_action/intention_capture_agent.py`'s private
`_is_stale` (and its `_STALE_AFTER_DEADLINE_DAYS` / `_STALE_NO_DEADLINE_DAYS`
/ `_TERMINAL_STATUSES` constants). ADR-021 (Phase 14) directs E1 to "reuse
its rule ... rather than inventing a second staleness definition," and to
extract it to a shared importable location if duplicating it would be
real duplication, "E1's call, document either way."

E1 cannot edit `backend/app/agents/intention_action/intention_capture_agent.py`
to redirect its own private `_is_stale` call site to import from here —
that file is E2-owned (`backend/app/agents/`, PHASES.md §1.1 hard file
ownership; gharos-standards skill: "An engineer may not edit files outside
their owned directories"). So this module is a genuine, acknowledged,
**temporary** duplication of that rule's logic and thresholds, copied
byte-for-byte (not reinterpreted or redefined), landed in `backend/app/
solvers/` — E1's own owned, established home for deterministic,
no-model-call business logic (`calibration_stats.py`, `fair_allocation.py`,
`salary_calculator.py` all already live here). **Flagged explicitly in
this phase's report to the CTO/E2:** the correct follow-up is a one-line
change in `intention_capture_agent.py` importing `is_stale` from here and
deleting its own private copy, eliminating the duplication for good — E1
is not authorized to make that edit itself.

Both copies must be kept in lock-step until that follow-up lands: a
change to either the thresholds or the rule here without a matching
change there (or vice versa) would silently reintroduce the "two
independent staleness definitions" failure mode ADR-021 explicitly warns
against.
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
was remembered and still didn't happen at the moment of action. Copied
verbatim from `intention_capture_agent._STALE_AFTER_DEADLINE_DAYS` — see
this module's docstring."""

_STALE_NO_DEADLINE_DAYS = 21
"""An `Obligation` with no `due_at` and no `must_start_by` at all (an
open-ended intention, spec's own "call the dentist" worked example) is
stale once its current version has sat untouched for this many days.
Copied verbatim from `intention_capture_agent._STALE_NO_DEADLINE_DAYS` —
see this module's docstring."""

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
