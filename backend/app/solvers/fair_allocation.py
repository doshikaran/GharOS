"""Deterministic fairness solver for the Fair Allocator (PHASES.md Phase 8,
E1 work item 1; spec §8.3 Stage 3 — "a deterministic isolated solver
computes the allocation. A code tool, not an LLM."; ADR-014, this phase's
binding, CTO-frozen algorithm choice).

**No LLM call anywhere in this module.** A17-A21 (E2, dispatched after
this module exists) elicit comparative preferences, extract a cardinal
cost matrix, and verify/explain this module's output — the algorithm
itself is pure, mechanical, and belongs in code.

**Phase 8, E2 addition:** `verify_ef1` (below `solve_fair_allocation`) is
the real, reusable EF1-checking function A19 (Fairness Verifier/Explainer)
and `backend/tests/test_fair_allocation.py`'s own
`TestEF1ExternalVerification` both call — added here, rather than as a
second implementation inside `app.agents.fair_allocator`, because it is
exactly as pure, mechanical, and LLM-free as the construction logic above
it (spec §8.3's "verify" stage is a deterministic step, just like
"solve"). This module is genuinely a shared solver-*and*-verification
module for the Fair Allocator as of this addition — it still makes no LLM
call and still takes no dependency on `app.agents.fair_allocator`.

## The algorithm (ADR-014 — do not deviate; this module implements it
## exactly, it does not re-derive or re-litigate it)

Fixed-order round-robin sequential picking: people are ordered once,
lexicographically by `NodeId` string, for the entire duration of one
`solve_fair_allocation` call — never adaptive, never reordered mid-solve.
On each person's turn, they take their least-cost remaining
*solve-feasible* task (see below); ties broken by task id, lexicographic.
This repeats, cycling through the fixed order, until every task is
assigned.

This is the classical round-robin-for-goods EF1 result (Lipton et al.
2004; the broader picking-sequences literature), applied to costs instead
of values via the identical exchange argument: at every one of a person's
own turns, any task another person eventually receives was available to
them at that moment, and they chose a task they liked at least as much
(cost at most as much) instead. `docs/FAIRNESS_GUARANTEE.md` is the
literal, code-matching statement of exactly what this delivers (EF1 for
additive costs) and does not deliver (Pareto-optimality) — this module's
behaviour and that document must never drift apart.

## "Solve-feasible" — how the two real input structures combine

This module takes two independent, real structures, per the E1 work
order:

- `costs` (`CostMatrix`): people x tasks, **sparse by omission** — a
  `(person_id, task_id)` pair absent from `costs[person_id]` means this
  person was never asked about this task, never a fabricated `0.0`
  (`contracts.graph_types.ValuationProfile`'s own docstring, spec §15.8
  A18's failure mode: "sparse matrix -> request coverage, never fabricate
  values").
- `feasibility` (`FeasibilityMap`): which person-task pairs are
  *capability*-eligible, independent of whether a cost was ever elicited
  for that pair.

A person-task pair is **solve-feasible** only when it is both
capability-eligible (present in `feasibility[person_id]`) *and* has a
known cost (present in `costs[person_id]`) — a real, documented judgment
call: this module cannot compute "least-cost" for a pair with no cost
value, so a capability-eligible-but-never-priced pair is excluded from
solving exactly as a capability-ineligible one is, and the pre-solve
orphan check (below) treats both as the same real failure to solve a
task, not two different problems.

## Capability constraints enforced pre-solve (ADR-014, Gate 8's own
## checklist item — never post-hoc filtered after an infeasible
## assignment already happened)

Solve-feasibility for every (person, task) pair is computed once, before
the round-robin loop runs, from `costs` and `feasibility` exactly as
given — the loop only ever chooses among pairs already known to be
solve-feasible. **A task with zero solve-feasible people anywhere raises
`OrphanedTaskError` naming the orphaned task(s)** — never silently
dropped, never force-assigned to an incapable or unpriced person. This
covers both real reasons a task cannot be solved: nobody is
capability-eligible for it, or the only capability-eligible person(s)
were never asked (no cost data) — see this module's final report for
which case a given orphan falls into.

A second, defensive-only invariant is enforced *during* the loop: a full
round-robin cycle (every person gets one turn) that produces zero new
assignments while tasks remain unassigned also raises `OrphanedTaskError`
— naming every still-unassigned task. Given the pre-solve check above and
no per-person capacity limit anywhere in this algorithm, this branch is
mathematically unreachable through `solve_fair_allocation` itself (every
task with >=1 solve-feasible person is guaranteed to be picked up by that
person eventually, since nobody is ever removed from the fixed rotation);
it exists as a runtime backstop against ever looping forever or returning
a silently-partial allocation if a future change to this module's own
logic broke that invariant. `_round_robin_pass` (module-private, exercised
directly by this module's own test suite with a deliberately
inconsistent internal state) is how that branch is tested, since it
cannot be triggered through the public, pre-validated entry point.

## A turn with no solve-feasible remaining task is skipped, not an error

Because different people may be solve-feasible for disjoint sets of
tasks, a person's turn can arrive with zero solve-feasible tasks left
(everything solve-feasible for them has already been assigned) — this is
the ordinary, well-known behaviour of picking sequences over unequal
eligibility sets (Bouveret & Lang; the broader picking-sequences
literature ADR-014 cites), not a failure. The turn is simply skipped
(no pick, no error) and the next person in the fixed order takes their
turn.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass

import structlog
from contracts.graph_types import NodeId

logger = structlog.get_logger(__name__)

CostMatrix = Mapping[NodeId, Mapping[NodeId, float]]
"""person_id -> {task_id -> this person's real cost for that task}. A
`task_id` absent from `costs[person_id]` means this person was never
asked about it — sparse by omission, never a fabricated `0.0` (see this
module's docstring)."""

FeasibilityMap = Mapping[NodeId, AbstractSet[NodeId]]
"""person_id -> the set of task ids this person is *capability*-eligible
for, independent of whether a cost was ever elicited for any of them."""


class FairAllocationError(Exception):
    """Base class for every typed error raised by
    `app.solvers.fair_allocation`. Mirrors the role
    `contracts.errors.GharOSError` plays for the graph and action layers
    (`contracts/errors.py` is frozen and CTO-owned) — this solver's own
    failure modes are local to its own algorithm, not the shared
    taxonomy, matching the precedent `app.graph.errors.GraphQueryError`
    and `app.persistence.errors.PersistenceError` already set."""


class OrphanedTaskError(FairAllocationError):
    """Raised when one or more tasks cannot be solved:

    - **Pre-solve** (the common, expected case): a task has zero
      solve-feasible people anywhere — nobody is both capability-eligible
      for it and has a known cost for it. Detected before the round-robin
      loop runs at all (ADR-014, Gate 8: "capability constraints enforced
      pre-solve").
    - **Mid-solve** (a defensive backstop, not reachable through
      `solve_fair_allocation`'s own pre-validated entry point — see this
      module's docstring): a full round-robin cycle completed with zero
      new assignments while tasks remain unassigned.

    Never silently dropped, never force-assigned, never looped forever
    on, never returned as a silently-partial allocation — this exception
    is the only way either condition surfaces.
    """

    def __init__(self, *, task_ids: tuple[NodeId, ...], reason: str) -> None:
        self.task_ids = task_ids
        self.reason = reason
        super().__init__(f"orphaned task(s) {list(task_ids)!r}: {reason}")


@dataclass(frozen=True, slots=True)
class AllocationPick:
    """One real pick made during the solve — the auditable "how did we
    get here" trail Gate 8's own EF1-checkability requirement, and A19
    (Verifier/Explainer, E2), need."""

    turn_index: int
    """0-based index of this pick among every pick made in this solve
    call, in the order picks actually happened — *not* every person's
    turn (a turn with no solve-feasible remaining task is skipped and
    does not consume a `turn_index`)."""
    round_number: int
    """0-based full round-robin cycle this pick happened in (cycle 0 is
    the fixed order's first full pass through every person)."""
    person_id: NodeId
    task_id: NodeId
    cost: float
    """`costs[person_id][task_id]` at the moment of this pick — the exact
    value this person's own valuation assigns to the task they took."""


@dataclass(frozen=True, slots=True)
class FairAllocationResult:
    """The solve's full, auditable output — not just the final
    assignment. Every field here is real, derived data, never
    re-computed by a caller from scratch, so `docs/FAIRNESS_GUARANTEE.md`'s
    own EF1 claim is directly checkable against it (Gate 8)."""

    allocation: dict[NodeId, NodeId]
    """task_id -> person_id. Every task_id passed to `solve_fair_allocation`
    appears here exactly once."""
    picks: tuple[AllocationPick, ...]
    """Every pick made, in the exact order it was made — the full
    round-robin trace."""
    person_total_cost: dict[NodeId, float]
    """person_id -> sum of `costs[person_id][t]` over every task `t`
    allocated to them. Present (at `0.0`) for every person in
    `person_ids`, including a person who received nothing."""
    order: tuple[NodeId, ...]
    """The fixed round-robin order actually used — `person_ids` sorted
    lexicographically by `NodeId` string, per ADR-014. Recorded on the
    result so a caller (or A19's Verifier) never has to re-derive it and
    risk it drifting from what was actually used."""


def _validate_inputs(
    person_ids: Sequence[NodeId],
    task_ids: Sequence[NodeId],
    costs: CostMatrix,
    feasibility: FeasibilityMap,
) -> tuple[frozenset[NodeId], frozenset[NodeId]]:
    if not person_ids:
        raise ValueError("person_ids must be non-empty")
    if not task_ids:
        raise ValueError("task_ids must be non-empty")
    if len(set(person_ids)) != len(person_ids):
        raise ValueError("person_ids must not contain duplicates")
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("task_ids must not contain duplicates")

    person_id_set = frozenset(person_ids)
    task_id_set = frozenset(task_ids)

    for person_id, task_cost_map in costs.items():
        if person_id not in person_id_set:
            raise ValueError(f"costs references unknown person_id {person_id!r}")
        for task_id, cost in task_cost_map.items():
            if task_id not in task_id_set:
                raise ValueError(f"costs[{person_id!r}] references unknown task_id {task_id!r}")
            if not math.isfinite(cost):
                raise ValueError(f"costs[{person_id!r}][{task_id!r}] = {cost!r} is not finite")
            if cost < 0:
                raise ValueError(
                    f"costs[{person_id!r}][{task_id!r}] = {cost!r} is negative — costs must be >= 0"
                )

    for person_id, eligible_tasks in feasibility.items():
        if person_id not in person_id_set:
            raise ValueError(f"feasibility references unknown person_id {person_id!r}")
        for task_id in eligible_tasks:
            if task_id not in task_id_set:
                raise ValueError(f"feasibility[{person_id!r}] references unknown task_id {task_id!r}")

    return person_id_set, task_id_set


def _solve_feasible_sets(
    person_id_set: frozenset[NodeId],
    costs: CostMatrix,
    feasibility: FeasibilityMap,
) -> dict[NodeId, set[NodeId]]:
    """capability-eligible ∩ cost-known, per person — see this module's
    docstring for why both conditions are required."""
    result: dict[NodeId, set[NodeId]] = {}
    for person_id in person_id_set:
        eligible = feasibility.get(person_id, frozenset())
        known_costs = costs.get(person_id, {})
        result[person_id] = {task_id for task_id in eligible if task_id in known_costs}
    return result


def _orphaned_tasks(
    task_id_set: frozenset[NodeId],
    solve_feasible: Mapping[NodeId, AbstractSet[NodeId]],
) -> tuple[NodeId, ...]:
    has_feasible_person: dict[NodeId, bool] = dict.fromkeys(task_id_set, False)
    for tasks in solve_feasible.values():
        for task_id in tasks:
            has_feasible_person[task_id] = True
    return tuple(sorted((t for t, has in has_feasible_person.items() if not has), key=str))


def _round_robin_pass(
    order: Sequence[NodeId],
    solve_feasible: Mapping[NodeId, AbstractSet[NodeId]],
    remaining_tasks: set[NodeId],
    costs: CostMatrix,
    *,
    round_number: int,
    next_turn_index: int,
) -> list[AllocationPick]:
    """Runs one full pass through `order` — each person takes (if
    possible) their least-cost remaining solve-feasible task. Mutates
    `remaining_tasks` in place (removes every task picked this pass).
    Returns the picks made, in order; an empty list means zero progress
    this pass — the caller (`solve_fair_allocation`) is responsible for
    turning that into `OrphanedTaskError`, this function only reports it
    by returning nothing.

    Module-private, but exercised directly (not only through
    `solve_fair_allocation`) by this module's own test suite to prove the
    zero-progress backstop actually fires — see this module's docstring
    on why that branch is unreachable through the public, pre-validated
    entry point."""
    picks: list[AllocationPick] = []
    turn_index = next_turn_index
    for person_id in order:
        if not remaining_tasks:
            break
        candidates = solve_feasible.get(person_id, set()) & remaining_tasks
        if not candidates:
            continue
        chosen_task = min(candidates, key=lambda t: (costs[person_id][t], str(t)))
        cost = costs[person_id][chosen_task]
        remaining_tasks.discard(chosen_task)
        picks.append(
            AllocationPick(
                turn_index=turn_index,
                round_number=round_number,
                person_id=person_id,
                task_id=chosen_task,
                cost=cost,
            )
        )
        turn_index += 1
    return picks


def solve_fair_allocation(
    *,
    person_ids: Sequence[NodeId],
    task_ids: Sequence[NodeId],
    costs: CostMatrix,
    feasibility: FeasibilityMap,
) -> FairAllocationResult:
    """Solves one Fair Allocator round: fixed-order round-robin sequential
    picking over a real, sparse, capability-constrained cost matrix
    (ADR-014). Deterministic — identical input always produces an
    identical `FairAllocationResult` (Gate 8: "identical input -> identical
    output"); no randomness, no wall-clock or environment dependence, no
    reliance on dict/set iteration order (the fixed order is an explicit
    lexicographic sort; every tie-break is fully deterministic).

    Args:
        person_ids: every person participating in this solve — the
            *unsorted* input; this function sorts them itself
            (lexicographically by `NodeId` string) to build the fixed
            round-robin order, per ADR-014. Must be non-empty, no
            duplicates.
        task_ids: every task to be allocated in this solve. Must be
            non-empty, no duplicates.
        costs: sparse people x tasks cost matrix — see `CostMatrix`'s own
            docstring. Every `person_id`/`task_id` referenced must be one
            of `person_ids`/`task_ids`; every cost must be finite and
            `>= 0`.
        feasibility: capability-eligibility per person — see
            `FeasibilityMap`'s own docstring. Every `person_id`/`task_id`
            referenced must be one of `person_ids`/`task_ids`.

    Returns:
        A `FairAllocationResult` with every task in `task_ids` allocated
        to exactly one person, plus the full auditable pick trail.

    Raises:
        ValueError: malformed input — empty/duplicate `person_ids` or
            `task_ids`, a `costs`/`feasibility` entry referencing an
            unknown person or task id, or a non-finite/negative cost.
        OrphanedTaskError: one or more tasks have zero solve-feasible
            people anywhere (pre-solve — the expected, documented failure
            mode), or a full round-robin cycle made zero progress with
            tasks still remaining (a defensive backstop; see this
            module's docstring).
    """
    person_id_set, task_id_set = _validate_inputs(person_ids, task_ids, costs, feasibility)
    solve_feasible = _solve_feasible_sets(person_id_set, costs, feasibility)

    orphaned = _orphaned_tasks(task_id_set, solve_feasible)
    if orphaned:
        raise OrphanedTaskError(
            task_ids=orphaned,
            reason=(
                "no person is both capability-eligible for and has a known cost for this task — "
                "enforced pre-solve, per ADR-014 and Gate 8's checklist"
            ),
        )

    order = tuple(sorted(person_id_set, key=str))
    remaining_tasks: set[NodeId] = set(task_id_set)
    all_picks: list[AllocationPick] = []
    person_total_cost: dict[NodeId, float] = dict.fromkeys(order, 0.0)

    round_number = 0
    while remaining_tasks:
        round_picks = _round_robin_pass(
            order,
            solve_feasible,
            remaining_tasks,
            costs,
            round_number=round_number,
            next_turn_index=len(all_picks),
        )
        if not round_picks:
            raise OrphanedTaskError(
                task_ids=tuple(sorted(remaining_tasks, key=str)),
                reason=(
                    "a full round-robin cycle completed with zero assignments while tasks remain "
                    "unassigned — every remaining task is solve-infeasible for every person this cycle"
                ),
            )
        for pick in round_picks:
            person_total_cost[pick.person_id] += pick.cost
        all_picks.extend(round_picks)
        round_number += 1

    allocation = {pick.task_id: pick.person_id for pick in all_picks}

    result = FairAllocationResult(
        allocation=allocation,
        picks=tuple(all_picks),
        person_total_cost=person_total_cost,
        order=order,
    )
    logger.info(
        "fair_allocation.completed",
        person_count=len(order),
        task_count=len(task_id_set),
        round_count=round_number,
        pick_count=len(all_picks),
    )
    return result


class IncompleteCostCoverageError(FairAllocationError):
    """Raised by `verify_ef1` when `costs` lacks a priced entry needed to
    compute the EF1 check for some ordered pair — never silently skipped,
    never treated as "holds". `docs/FAIRNESS_GUARANTEE.md` §3 is explicit
    that the EF1 guarantee itself is scoped to each person's *own*
    solve-feasible tasks; checking it against a task a person was never
    priced for is not a weaker form of the same check, it is a different,
    uncomputable question — this exception is how that distinction stays
    visible rather than silently defaulting to "no violation found"."""

    def __init__(self, *, envier: NodeId, envied: NodeId, missing_task_id: NodeId) -> None:
        self.envier = envier
        self.envied = envied
        self.missing_task_id = missing_task_id
        super().__init__(
            f"cannot verify EF1 for ({envier!r} vs {envied!r}): {envier!r} has no priced "
            f"cost for task {missing_task_id!r}"
        )


@dataclass(frozen=True, slots=True)
class EF1Violation:
    """One ordered pair for which EF1 does not hold — see this module's
    own "why round-robin delivers this" docstring section and
    `docs/FAIRNESS_GUARANTEE.md` §1 for the exact property being checked
    (the "remove from the envier's own bundle" chore-EF1 definition, not
    the goods-EF1 "remove from the envied bundle" one)."""

    envier: NodeId
    envied: NodeId
    envier_own_bundle_cost: float
    envier_cost_for_envied_bundle: float
    envier_worst_own_item_cost: float


def verify_ef1(result: FairAllocationResult, costs: CostMatrix) -> tuple[EF1Violation, ...]:
    """Independent, external EF1 check on an already-produced
    `FairAllocationResult` — the real, reusable, production version of the
    exact standalone check `backend/tests/test_fair_allocation.py`'s
    `TestEF1ExternalVerification` already proved correct on four distinct
    worked scenarios (that test module now delegates its own assertion
    helper to this function, so there is exactly one EF1-checking
    implementation in this codebase, never two that could drift apart).

    Deliberately duplicates none of `solve_fair_allocation`'s own
    internals — no call to `_round_robin_pass` or any other module-private
    helper. It re-derives each person's bundle from `result.allocation`
    alone and checks the EF1 property directly from its own definition, so
    a bug in the round-robin construction logic above could not, by
    construction, also corrupt this check into agreeing with it (the
    entire point of an *external* checkable signal, per spec §8.3's
    "verify and explain" stage and A19's own "deliberately avoids LLM
    self-critique" design note — the analogous discipline applied to
    non-LLM code review of the solver's own output).

    This is genuinely a verification function living alongside
    `solve_fair_allocation`'s construction logic in the same module, not a
    second solver: it takes a `FairAllocationResult` as *input* and never
    calls `solve_fair_allocation` itself, so this module remains a single,
    pure, LLM-free unit (its own module docstring's "no LLM call anywhere
    in this module" claim is unaffected) that is now honestly described as
    a shared solver-*and*-verification module for the Fair Allocator,
    matching what spec §8.3's own "solve" and "verify" stages actually
    are: two adjacent, both-deterministic steps, not one.

    Args:
        result: a `FairAllocationResult` from `solve_fair_allocation`.
        costs: the exact `CostMatrix` that produced `result` (or an
            equally-complete one) — must have, for every person in
            `result.order`, a priced cost for every task in their own
            bundle AND every task in every other person's bundle. This is
            a stricter requirement than `solve_fair_allocation` itself
            needs (which only requires the *assigned* recipient to have
              priced a task) — see `IncompleteCostCoverageError`.

    Returns:
        A tuple of every ordered-pair `EF1Violation` found — empty means
        EF1 holds for every ordered pair of people in `result.order`.

    Raises:
        IncompleteCostCoverageError: `costs` lacks a priced entry needed
            to compute the check for some ordered pair.
    """
    bundles: dict[NodeId, set[NodeId]] = {person_id: set() for person_id in result.order}
    for task_id, person_id in result.allocation.items():
        bundles.setdefault(person_id, set()).add(task_id)

    violations: list[EF1Violation] = []
    for envier in result.order:
        own_bundle = bundles[envier]
        if not own_bundle:
            continue  # an empty bundle cannot envy anyone (nothing to remove, no own cost)
        envier_costs = costs.get(envier, {})
        for task_id in own_bundle:
            if task_id not in envier_costs:
                raise IncompleteCostCoverageError(envier=envier, envied=envier, missing_task_id=task_id)
        own_cost = sum(envier_costs[t] for t in own_bundle)
        worst_own_item_cost = max(envier_costs[t] for t in own_bundle)

        for envied in result.order:
            if envied == envier:
                continue
            envied_bundle = bundles[envied]
            for task_id in envied_bundle:
                if task_id not in envier_costs:
                    raise IncompleteCostCoverageError(envier=envier, envied=envied, missing_task_id=task_id)
            envied_cost_to_envier = sum(envier_costs[t] for t in envied_bundle)
            if (own_cost - worst_own_item_cost) > envied_cost_to_envier:
                violations.append(
                    EF1Violation(
                        envier=envier,
                        envied=envied,
                        envier_own_bundle_cost=own_cost,
                        envier_cost_for_envied_bundle=envied_cost_to_envier,
                        envier_worst_own_item_cost=worst_own_item_cost,
                    )
                )
    return tuple(violations)


__all__ = [
    "AllocationPick",
    "CostMatrix",
    "EF1Violation",
    "FairAllocationError",
    "FairAllocationResult",
    "FeasibilityMap",
    "IncompleteCostCoverageError",
    "OrphanedTaskError",
    "solve_fair_allocation",
    "verify_ef1",
]
