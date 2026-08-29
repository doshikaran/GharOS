"""Deterministic mechanism arbiter for the Household Council (PHASES.md
Phase 12, E1 work item 1; spec §12.3 Phase 6 — "a deterministic arbiter
computes the outcome from the published interest scores and constraints";
ADR-019 Decision 3, this phase's binding, CTO-frozen algorithm choice).

**No LLM call anywhere in this module. No graph I/O anywhere in this
module.** Mirrors `fair_allocation.py`'s (Phase 8) and
`calibration_stats.py`'s (Phase 11) established shape exactly: a pure
function over plain data, handed already-fetched real inputs by its
caller (A49 Council Recorder, deterministic, no model call itself — spec
§15.9's own status for A49, ADR-019 Decision 5).

## The algorithm — minimax regret with leximin refinement (ADR-019
## Decision 3; do not deviate; this module implements it exactly, it does
## not re-derive or re-litigate it)

**Why not Maximum Nash Welfare or a utilitarian sum** (both real,
legitimate mechanisms for a *different* problem shape): every delegate's
`ValuationProfile.costs` is only ever claimed comparable *within* that one
person's own matrix (spec: "arbitrary-but-consistent unit ... across one
household's whole matrix") — never comparable *across* people. A raw
utilitarian sum or MNW's product-of-utilities would silently assert an
inter-personal comparability this system has never earned, exactly the
kind of unearned precision this project refuses everywhere else (ADR-014's
own chores/goods distinction; Phase 9/11's thin-history honesty).

**Decision (Savage, 1951 — a real, standard decision-theory criterion, not
invented for this project):** for each surviving option `o` and delegate
`i`, `regret_i(o) = cost_i(o) - min(cost_i(o') for o' in surviving options
that delegate i actually priced)` — how much worse `o` is for person `i`
than *that same person's own* best surviving option. This never compares
raw cost units across people; it only ever compares a person's cost
against their own other options. The winner minimizes the maximum regret
across all delegates (minimax regret); ties are broken by **leximin
refinement** (compare the next-highest regret, then the next — a
standard, well-founded refinement of egalitarian/minimax social choice
rules, not an arbitrary tiebreak); a final, explicit, documented arbitrary
tiebreak (lexical `branch_id` order) only if a genuine leximin tie
survives (matching this project's own precedent of naming an
arbitrary-but-deterministic final tiebreak outright rather than leaving
one implicit — Phase 11's `RankedOutcome` tie-breaking).

**Implementation note — one sort achieves both minimax and leximin.**
Each candidate branch's regret values (across whichever delegates priced
it) are sorted descending into a tuple; the branch whose tuple is
lexicographically smallest wins. The first element of a descending-sorted
tuple *is* that branch's maximum regret, so ordinary tuple comparison
already implements "minimize the maximum regret, then the second-highest,
then the third" in one `min(..., key=...)` call — leximin refinement is
not a separate pass, it falls out of comparing full sorted tuples instead
of just their first element. `str(branch_id)` is appended as the tuple's
final element so a genuine, complete tie is still resolved deterministically
by lexical branch id, never by dict/set iteration order.

**Hard constraints eliminate before this function ever runs.** A43 Care's
`HARD`-severity constraints (and any other specialist's `HARD` constraint)
prune the surviving-branch set during Phase 4 interest scoring, before
`resolve()` is ever called (Gate 12: "hard constraint ELIMINATES options,
does not score them down"). `resolve()` itself enforces this
structurally, not just by convention: it only ever reads costs keyed by a
`surviving_branch_ids` entry, and only ever selects a winner from that set
— an `eliminated_branch_ids` entry can never become `winning_branch_id`
regardless of what (if anything) a `ValuationProfile.costs` dict happens
to contain for it.

## The sparse-cost policy — documented, never a fabricated 0.0 or ∞

`ValuationProfile.costs` is sparse by omission (spec: never fabricate a
missing value as `0.0`) exactly like `fair_allocation.py`'s `CostMatrix`.
This module's documented policy, at two distinct granularities:

1. **A delegate with zero priced surviving branches** (never asked about
   any of this decision's options, or asked and gave no usable answer) has
   no basis for even its own reference minimum — that delegate is excluded
   from **every** branch's regret computation entirely, contributing
   nothing anywhere, rather than being silently assigned a fabricated
   regret of `0.0` (which would understate every option's true cost to
   them) or of `+inf` (which would make every option they didn't price
   look catastrophic).
2. **A delegate with a priced subset of surviving branches** (the common,
   expected case — not every delegate answers about every option)
   contributes its own reference minimum from the branches it *did* price,
   and is excluded only from the regret computation of the specific
   branch(es) it never priced — never fabricated as free (`0.0`, which
   would make that branch look artificially attractive) or infinitely bad
   (which would make it look artificially eliminated, achieving by the
   back door exactly the scoring-down Gate 12 forbids for hard
   constraints).

A branch that ends up with zero contributing delegates (nobody priced it
at all) is excluded from the candidate winner pool entirely — it is not
`0.0` regret (unearned) nor `+inf` (fabricated elimination); there is
simply no signal to judge it by. If *every* surviving branch ends up in
that state, `NoCostSignalError` is raised (see below) rather than
returning an arbitrary or `None` winner.

**A genuine leximin tie between regret vectors of different lengths**
(possible only when the sparse-cost policy above has excluded a different
number of delegates from two tied branches) is resolved by ordinary
Python tuple comparison: a shorter vector that is a true prefix of a
longer, otherwise-equal one compares as smaller and wins the tie. This is
a real, if rare, corner case — documented here explicitly, exercised by
this module's own test suite, rather than left as an unnoticed side
effect of the tuple-comparison implementation.
"""

from __future__ import annotations

from dataclasses import dataclass

import structlog
from contracts.graph_types import NodeId, ValuationProfile

logger = structlog.get_logger(__name__)


class CouncilArbiterError(Exception):
    """Base class for every typed error raised by
    `app.solvers.council_arbiter`. Mirrors the role
    `app.solvers.fair_allocation.FairAllocationError` plays for that
    module — this solver's own failure modes are local to its own
    algorithm, not the shared `contracts.errors` taxonomy."""


class NoSurvivingBranchesError(CouncilArbiterError):
    """`surviving_branch_ids` was empty — nothing to resolve. Never
    silently returns a `None`/fabricated winner."""

    def __init__(self) -> None:
        super().__init__("surviving_branch_ids must be non-empty — nothing to resolve")


class NoCostSignalError(CouncilArbiterError):
    """Not a single `ValuationProfile` has a real cost for any surviving
    branch — genuinely no signal to resolve from. Never silently
    fabricates a winner from no evidence (see this module's docstring,
    "the sparse-cost policy")."""

    def __init__(self) -> None:
        super().__init__(
            "no ValuationProfile has a real cost for any surviving branch — "
            "genuinely no signal to resolve from; refusing to fabricate a winner"
        )


@dataclass(frozen=True, slots=True)
class CouncilResolution:
    """The arbiter's full, auditable output — not just the winner. Every
    field here is real, derived data traceable to a real
    `ValuationProfile.costs` entry (ADR-019 Decision 3's "the trade-off
    statement, computed not narrated")."""

    winning_branch_id: NodeId
    regret_by_person: dict[NodeId, float]
    """`ValuationProfile.person_id` -> that person's real regret for the
    winning branch. Sparse by the same policy as the input: a person whose
    profile never priced the winning branch has no entry here (never a
    fabricated `0.0`)."""
    most_costly_to: NodeId | None
    """The person with the highest regret for the winner — who "loses"
    most (ADR-019 Decision 3). `None` only if `regret_by_person` is empty
    (structurally unreachable through `resolve()`'s own public entry point
    — a winning branch is only ever chosen from candidates with at least
    one contributing profile — kept `| None` for defensive type honesty,
    matching this project's precedent of typing a theoretically-impossible-
    through-the-public-API case rather than asserting it away)."""
    most_favorable_to: NodeId | None
    """The person with the lowest regret for the winner — at or near their
    own top pick. Same `None` caveat as `most_costly_to`."""
    conceding_person_ids: tuple[NodeId, ...]
    """Every person with `regret_by_person[person_id] > 0` for the winner
    — a real concession (ADR-019 Decision 3: "every delegate with
    regret_i(winner) > 0 is a real concession"). Sorted lexicographically
    by `NodeId` string for deterministic output. A49 Recorder writes a
    `CONCEDED_BY` edge for each of these."""
    eliminated_branch_ids: tuple[NodeId, ...]
    """Echoed straight from the caller's own input, in the order given —
    kept on the result so it is self-contained for audit without a caller
    needing to separately retain what was eliminated before scoring."""


def _validate_inputs(
    surviving_branch_ids: tuple[NodeId, ...],
    eliminated_branch_ids: tuple[NodeId, ...],
    valuation_profiles: tuple[ValuationProfile, ...],
) -> None:
    if not surviving_branch_ids:
        raise NoSurvivingBranchesError()
    if len(set(surviving_branch_ids)) != len(surviving_branch_ids):
        raise ValueError("surviving_branch_ids must not contain duplicates")
    if len(set(eliminated_branch_ids)) != len(eliminated_branch_ids):
        raise ValueError("eliminated_branch_ids must not contain duplicates")
    overlap = frozenset(surviving_branch_ids) & frozenset(eliminated_branch_ids)
    if overlap:
        raise ValueError(
            f"branch id(s) {sorted(str(b) for b in overlap)!r} appear in both "
            "surviving_branch_ids and eliminated_branch_ids"
        )
    seen_person_ids: set[NodeId] = set()
    for profile in valuation_profiles:
        if profile.person_id in seen_person_ids:
            raise ValueError(f"duplicate ValuationProfile for person_id {profile.person_id!r}")
        seen_person_ids.add(profile.person_id)


def _regret_by_branch(
    surviving_branch_ids: tuple[NodeId, ...],
    valuation_profiles: tuple[ValuationProfile, ...],
) -> dict[NodeId, dict[NodeId, float]]:
    """`branch_id -> {person_id -> regret}` — sparse per this module's
    documented policy. A profile with zero priced surviving branches
    contributes no entry anywhere; a profile missing a price for one
    surviving branch contributes no entry for that branch specifically
    while still contributing its real regrets for the branches it did
    price."""
    regret: dict[NodeId, dict[NodeId, float]] = {branch_id: {} for branch_id in surviving_branch_ids}

    for profile in valuation_profiles:
        priced = {
            branch_id: profile.costs[str(branch_id)]
            for branch_id in surviving_branch_ids
            if str(branch_id) in profile.costs
        }
        if not priced:
            continue  # zero signal from this profile at all — excluded entirely, see policy above
        reference_min = min(priced.values())
        for branch_id, cost in priced.items():
            regret[branch_id][profile.person_id] = cost - reference_min

    return regret


def resolve(
    *,
    surviving_branch_ids: tuple[NodeId, ...],
    eliminated_branch_ids: tuple[NodeId, ...],
    valuation_profiles: tuple[ValuationProfile, ...],
) -> CouncilResolution:
    """Minimax regret with leximin refinement (ADR-019 Decision 3, Savage
    1951) — see this module's docstring for the full mathematical
    rationale and the documented sparse-cost policy.

    Args:
        surviving_branch_ids: options that survived hard-constraint
            elimination (Phase 4 interest scoring's own pre-pass, run
            *before* this function is ever called) — the only branches
            eligible to win. Must be non-empty, no duplicates.
        eliminated_branch_ids: options a `HARD` constraint removed before
            scoring — echoed onto the result for audit; never read for
            cost lookups and never selectable, structurally (see this
            module's docstring). No duplicates; must not overlap
            `surviving_branch_ids`.
        valuation_profiles: one delegate's real cost matrix per relevant
            household member (ADR-019 Decision 4 — decision-scoped, keyed
            by `str(branch_id)`). At most one profile per `person_id`.

    Returns:
        A `CouncilResolution` naming the winning branch, the real,
        traceable per-person regret it caused, who it cost most/favoured
        most, and every real concession.

    Raises:
        ValueError: malformed input — duplicate/overlapping branch ids, or
            more than one `ValuationProfile` for the same person.
        NoSurvivingBranchesError: `surviving_branch_ids` is empty.
        NoCostSignalError: not a single profile has a real cost for any
            surviving branch — genuinely no signal to resolve from.
    """
    _validate_inputs(surviving_branch_ids, eliminated_branch_ids, valuation_profiles)

    regret = _regret_by_branch(surviving_branch_ids, valuation_profiles)
    candidate_branch_ids = tuple(branch_id for branch_id in surviving_branch_ids if regret[branch_id])
    if not candidate_branch_ids:
        raise NoCostSignalError()

    def _leximin_key(branch_id: NodeId) -> tuple[tuple[float, ...], str]:
        descending_regrets = tuple(sorted(regret[branch_id].values(), reverse=True))
        return (descending_regrets, str(branch_id))

    winning_branch_id = min(candidate_branch_ids, key=_leximin_key)
    winner_regret = dict(regret[winning_branch_id])

    most_costly_to: NodeId | None = None
    most_favorable_to: NodeId | None = None
    if winner_regret:
        most_costly_to = min(
            (person_id for person_id in winner_regret),
            key=lambda person_id: (-winner_regret[person_id], str(person_id)),
        )
        most_favorable_to = min(
            (person_id for person_id in winner_regret),
            key=lambda person_id: (winner_regret[person_id], str(person_id)),
        )

    conceding_person_ids = tuple(
        sorted(
            (person_id for person_id, value in winner_regret.items() if value > 0),
            key=str,
        )
    )

    result = CouncilResolution(
        winning_branch_id=winning_branch_id,
        regret_by_person=winner_regret,
        most_costly_to=most_costly_to,
        most_favorable_to=most_favorable_to,
        conceding_person_ids=conceding_person_ids,
        eliminated_branch_ids=eliminated_branch_ids,
    )
    logger.info(
        "council_arbiter.resolved",
        winning_branch_id=str(winning_branch_id),
        candidate_count=len(candidate_branch_ids),
        conceding_count=len(conceding_person_ids),
    )
    return result


__all__ = [
    "CouncilArbiterError",
    "CouncilResolution",
    "NoCostSignalError",
    "NoSurvivingBranchesError",
    "resolve",
]
