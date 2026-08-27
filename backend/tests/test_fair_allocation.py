"""Tests for `app.solvers.fair_allocation.solve_fair_allocation` (PHASES.md
Phase 8, ADR-014).

Pure unit tests, no Firestore emulator involved — `solve_fair_allocation`
does no graph I/O (see the module's own docstring), so every scenario here
is constructed from plain `NodeId` strings and dict/set literals, matching
the E1 charter's "fully unit-testable with no mocking" requirement.

`TestEF1ExternalVerification` is the "genuinely important" honest check
this phase's work order calls for: it checks whether EF1 holds on a
produced allocation via `app.solvers.fair_allocation.verify_ef1` — a
function that duplicates none of `solve_fair_allocation`'s own internals
— an independent, external check, not a tautological one. (Phase 8, E2
addition: `verify_ef1` was promoted from a test-only local helper into
real, reusable production code once A19 — Fairness Verifier/Explainer —
needed the exact same check; this test module now calls that shared
function instead of maintaining its own separate copy, so there is
exactly one EF1-checking implementation in the codebase.) It uses the
standard chore-EF1 definition (Aziz, Caragiannis, Igarashi, Walsh 2022 and
the broader chore-fair-division literature ADR-014 cites): an allocation
is EF1 if, for every ordered pair (A, B), removing A's own single
most-expensive-to-A item from A's bundle would make A no worse off than
B's bundle, i.e.
`cost_A(bundle_A) - max_item_cost_to_A(bundle_A) <= cost_A(bundle_B)`.
This is the "remove from the envier's own bundle" formulation that the
round-robin exchange argument (ADR-014's own reasoning, and this module's
docstring) actually proves — not the "remove from the envied bundle"
formulation goods-EF1 uses, which is a materially different (and, for
chores, incorrect) check: removing an item from the *envied* bundle makes
that bundle cheaper for the comparison, which only ever makes envy look
*worse*, not better, and is not the property round-robin picking of
chores delivers or ADR-014 claims.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import pytest
from contracts.graph_types import NodeId

from app.solvers.fair_allocation import (
    AllocationPick,
    FairAllocationResult,
    OrphanedTaskError,
    _round_robin_pass,  # noqa: PLC2701 -- deliberate white-box test of an otherwise-unreachable backstop, see module docstring
    solve_fair_allocation,
    verify_ef1,
)


def _pid(raw: str) -> NodeId:
    return NodeId(raw)


def _tid(raw: str) -> NodeId:
    return NodeId(raw)


def _row(*pairs: tuple[str, float]) -> dict[NodeId, float]:
    """Builds one person's cost row from `(task_id, cost)` pairs — a small
    formatting helper so dense multi-task cost matrices below stay within
    this file's line-length limit without sacrificing readability."""
    return {_tid(task_id): cost for task_id, cost in pairs}


# ---------------------------------------------------------------------------
# Basic solving, determinism, ordering
# ---------------------------------------------------------------------------


class TestBasicSolve:
    def test_every_task_allocated_exactly_once(self) -> None:
        result = solve_fair_allocation(
            person_ids=[_pid("p-1"), _pid("p-2")],
            task_ids=[_tid("t-1"), _tid("t-2"), _tid("t-3")],
            costs={
                _pid("p-1"): {_tid("t-1"): 5.0, _tid("t-2"): 5.0, _tid("t-3"): 1.0},
                _pid("p-2"): {_tid("t-1"): 1.0, _tid("t-2"): 1.0, _tid("t-3"): 10.0},
            },
            feasibility={
                _pid("p-1"): frozenset({_tid("t-1"), _tid("t-2"), _tid("t-3")}),
                _pid("p-2"): frozenset({_tid("t-1"), _tid("t-2"), _tid("t-3")}),
            },
        )
        assert set(result.allocation.keys()) == {_tid("t-1"), _tid("t-2"), _tid("t-3")}
        assert set(result.allocation.values()) <= {_pid("p-1"), _pid("p-2")}
        assert len(result.picks) == 3

    def test_fixed_order_is_lexicographic_regardless_of_input_order(self) -> None:
        """ADR-014: the round-robin order is a fixed lexicographic sort of
        `NodeId` strings, computed by the solver itself — never trusting
        (or preserving) whatever order the caller happened to pass
        `person_ids` in."""
        result = solve_fair_allocation(
            person_ids=[_pid("p-zebra"), _pid("p-apple")],
            task_ids=[_tid("t-1")],
            costs={_pid("p-zebra"): {_tid("t-1"): 1.0}, _pid("p-apple"): {_tid("t-1"): 1.0}},
            feasibility={
                _pid("p-zebra"): frozenset({_tid("t-1")}),
                _pid("p-apple"): frozenset({_tid("t-1")}),
            },
        )
        assert result.order == (_pid("p-apple"), _pid("p-zebra"))

    def test_person_total_cost_present_for_person_with_no_assignment(self) -> None:
        """A person included in `person_ids` who receives nothing still
        appears in `person_total_cost` at `0.0` — never silently absent."""
        result = solve_fair_allocation(
            person_ids=[_pid("p-1"), _pid("p-2")],
            task_ids=[_tid("t-1")],
            costs={_pid("p-1"): {_tid("t-1"): 1.0}, _pid("p-2"): {_tid("t-1"): 2.0}},
            feasibility={
                _pid("p-1"): frozenset({_tid("t-1")}),
                _pid("p-2"): frozenset({_tid("t-1")}),
            },
        )
        assert result.allocation[_tid("t-1")] == _pid("p-1")
        assert result.person_total_cost[_pid("p-1")] == 1.0
        assert result.person_total_cost[_pid("p-2")] == 0.0

    def test_person_with_no_solve_feasible_task_on_a_turn_is_skipped_not_an_error(self) -> None:
        """A person's turn with zero solve-feasible remaining tasks is
        simply skipped — ordinary picking-sequences behaviour when
        eligibility sets are unequal, never an error (module docstring)."""
        # p-1 is only feasible for t-1; p-2 is feasible for both. p-1 takes
        # t-1 on the first round; on p-1's later turns (if any) with t-1
        # already gone, p-1 has nothing left and must be skipped.
        result = solve_fair_allocation(
            person_ids=[_pid("p-1"), _pid("p-2")],
            task_ids=[_tid("t-1"), _tid("t-2")],
            costs={
                _pid("p-1"): {_tid("t-1"): 1.0},
                _pid("p-2"): {_tid("t-1"): 5.0, _tid("t-2"): 2.0},
            },
            feasibility={
                _pid("p-1"): frozenset({_tid("t-1")}),
                _pid("p-2"): frozenset({_tid("t-1"), _tid("t-2")}),
            },
        )
        assert result.allocation[_tid("t-1")] == _pid("p-1")
        assert result.allocation[_tid("t-2")] == _pid("p-2")


class TestDeterminism:
    def test_identical_input_produces_identical_output(self) -> None:
        """Gate 8: 'identical input -> identical output.'"""
        kwargs: dict[str, object] = {
            "person_ids": [_pid("p-1"), _pid("p-2"), _pid("p-3")],
            "task_ids": [_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4"), _tid("t-5")],
            "costs": {
                _pid("p-1"): _row(("t-1", 2.0), ("t-2", 6.0), ("t-3", 7.0), ("t-4", 1.0), ("t-5", 9.0)),
                _pid("p-2"): _row(("t-1", 8.0), ("t-2", 1.0), ("t-3", 2.0), ("t-4", 9.0), ("t-5", 3.0)),
                _pid("p-3"): _row(("t-1", 9.0), ("t-2", 9.0), ("t-3", 1.0), ("t-4", 8.0), ("t-5", 2.0)),
            },
            "feasibility": {
                _pid("p-1"): frozenset({_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4"), _tid("t-5")}),
                _pid("p-2"): frozenset({_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4"), _tid("t-5")}),
                _pid("p-3"): frozenset({_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4"), _tid("t-5")}),
            },
        }
        first = solve_fair_allocation(**kwargs)  # type: ignore[arg-type]
        second = solve_fair_allocation(**kwargs)  # type: ignore[arg-type]
        assert first == second
        assert repr(first) == repr(second)


class TestTieBreak:
    def test_ties_broken_by_lexicographic_task_id(self) -> None:
        """ADR-014: 'Ties within one person's turn ... break on task id,
        lexicographic.'"""
        result = solve_fair_allocation(
            person_ids=[_pid("p-1")],
            task_ids=[_tid("t-zebra"), _tid("t-apple"), _tid("t-mango")],
            costs={
                _pid("p-1"): {_tid("t-zebra"): 1.0, _tid("t-apple"): 1.0, _tid("t-mango"): 1.0},
            },
            feasibility={
                _pid("p-1"): frozenset({_tid("t-zebra"), _tid("t-apple"), _tid("t-mango")}),
            },
        )
        # All three tasks tie at cost 1.0 for the sole person; each of their
        # three consecutive turns must pick lexicographically, in order.
        first_pick, second_pick, third_pick = result.picks
        assert first_pick.task_id == _tid("t-apple")
        assert second_pick.task_id == _tid("t-mango")
        assert third_pick.task_id == _tid("t-zebra")


# ---------------------------------------------------------------------------
# Capability constraints — enforced pre-solve, never post-hoc
# ---------------------------------------------------------------------------


class TestCapabilityConstraints:
    def test_ineligible_person_never_receives_the_task_even_when_cheapest_for_them(self) -> None:
        """p-1 is cheapest for t-1 but not capability-eligible for it —
        must never receive it, regardless of cost."""
        result = solve_fair_allocation(
            person_ids=[_pid("p-1"), _pid("p-2")],
            task_ids=[_tid("t-1")],
            costs={_pid("p-1"): {_tid("t-1"): 0.5}, _pid("p-2"): {_tid("t-1"): 99.0}},
            feasibility={
                _pid("p-1"): frozenset(),  # not eligible for t-1 at all
                _pid("p-2"): frozenset({_tid("t-1")}),
            },
        )
        assert result.allocation[_tid("t-1")] == _pid("p-2")

    def test_capability_eligible_but_never_priced_pair_is_excluded_from_solving(self) -> None:
        """p-1 is capability-eligible for t-1 but has no cost entry for it
        (never asked) — this module cannot compute 'least-cost' for that
        pair, so it is excluded from solve-feasibility exactly as an
        ineligible pair would be (module docstring: 'solve-feasible')."""
        result = solve_fair_allocation(
            person_ids=[_pid("p-1"), _pid("p-2")],
            task_ids=[_tid("t-1")],
            costs={_pid("p-2"): {_tid("t-1"): 3.0}},  # p-1 has no entry for t-1 at all
            feasibility={
                _pid("p-1"): frozenset({_tid("t-1")}),  # capability-eligible...
                _pid("p-2"): frozenset({_tid("t-1")}),
            },
        )
        assert result.allocation[_tid("t-1")] == _pid("p-2")


class TestOrphanedTaskPreSolve:
    def test_task_with_no_capability_eligible_person_anywhere_raises(self) -> None:
        with pytest.raises(OrphanedTaskError) as exc_info:
            solve_fair_allocation(
                person_ids=[_pid("p-1"), _pid("p-2")],
                task_ids=[_tid("t-1"), _tid("t-orphan")],
                costs={
                    _pid("p-1"): {_tid("t-1"): 1.0, _tid("t-orphan"): 5.0},
                    _pid("p-2"): {_tid("t-1"): 2.0},
                },
                feasibility={
                    _pid("p-1"): frozenset({_tid("t-1")}),  # not eligible for t-orphan
                    _pid("p-2"): frozenset({_tid("t-1")}),  # not eligible for t-orphan either
                },
            )
        assert exc_info.value.task_ids == (_tid("t-orphan"),)

    def test_task_eligible_for_someone_but_priced_for_no_one_raises(self) -> None:
        """The other real reason a task can't be solved: someone is
        capability-eligible but nobody was ever asked their cost for it."""
        with pytest.raises(OrphanedTaskError) as exc_info:
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-orphan")],
                costs={},  # p-1 never priced anything
                feasibility={_pid("p-1"): frozenset({_tid("t-orphan")})},
            )
        assert exc_info.value.task_ids == (_tid("t-orphan"),)

    def test_multiple_orphaned_tasks_all_named(self) -> None:
        with pytest.raises(OrphanedTaskError) as exc_info:
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-orphan-a"), _tid("t-orphan-b")],
                costs={},
                feasibility={_pid("p-1"): frozenset()},
            )
        assert exc_info.value.task_ids == (_tid("t-orphan-a"), _tid("t-orphan-b"))


class TestOrphanedTaskMidSolveBackstop:
    """Exercises the defensive, otherwise-unreachable-through-the-public-
    entry-point backstop directly (module docstring explains why: given
    the pre-solve check and no per-person capacity limit, this branch
    cannot occur through `solve_fair_allocation` itself)."""

    def test_zero_progress_round_raises_via_public_entry_point_wiring(self) -> None:
        """A hand-built, internally-inconsistent state (a task marked
        solve-feasible for a person who is *not* in the round-robin
        `order` passed to `_round_robin_pass`) reproduces the same
        zero-progress condition `solve_fair_allocation`'s own loop would
        detect and turn into `OrphanedTaskError`."""
        remaining: set[NodeId] = {_tid("t-stuck")}
        picks = _round_robin_pass(
            order=(_pid("p-not-the-feasible-one"),),
            solve_feasible={_pid("p-actually-feasible"): {_tid("t-stuck")}},
            remaining_tasks=remaining,
            costs={_pid("p-actually-feasible"): {_tid("t-stuck"): 1.0}},
            round_number=0,
            next_turn_index=0,
        )
        assert picks == []
        assert remaining == {_tid("t-stuck")}  # zero progress: nothing removed


# ---------------------------------------------------------------------------
# Input validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_person_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="person_ids"):
            solve_fair_allocation(person_ids=[], task_ids=[_tid("t-1")], costs={}, feasibility={})

    def test_empty_task_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="task_ids"):
            solve_fair_allocation(person_ids=[_pid("p-1")], task_ids=[], costs={}, feasibility={})

    def test_duplicate_person_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            solve_fair_allocation(
                person_ids=[_pid("p-1"), _pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-1"): {_tid("t-1"): 1.0}},
                feasibility={_pid("p-1"): frozenset({_tid("t-1")})},
            )

    def test_duplicate_task_ids_rejected(self) -> None:
        with pytest.raises(ValueError, match="duplicate"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1"), _tid("t-1")],
                costs={_pid("p-1"): {_tid("t-1"): 1.0}},
                feasibility={_pid("p-1"): frozenset({_tid("t-1")})},
            )

    def test_costs_referencing_unknown_person_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown person_id"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-ghost"): {_tid("t-1"): 1.0}},
                feasibility={_pid("p-1"): frozenset({_tid("t-1")})},
            )

    def test_costs_referencing_unknown_task_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown task_id"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-1"): {_tid("t-ghost"): 1.0}},
                feasibility={_pid("p-1"): frozenset({_tid("t-1")})},
            )

    def test_feasibility_referencing_unknown_person_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown person_id"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-1"): {_tid("t-1"): 1.0}},
                feasibility={_pid("p-ghost"): frozenset({_tid("t-1")})},
            )

    def test_feasibility_referencing_unknown_task_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown task_id"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-1"): {_tid("t-1"): 1.0}},
                feasibility={_pid("p-1"): frozenset({_tid("t-ghost")})},
            )

    def test_negative_cost_rejected(self) -> None:
        with pytest.raises(ValueError, match="negative"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-1"): {_tid("t-1"): -1.0}},
                feasibility={_pid("p-1"): frozenset({_tid("t-1")})},
            )

    def test_non_finite_cost_rejected(self) -> None:
        with pytest.raises(ValueError, match="not finite"):
            solve_fair_allocation(
                person_ids=[_pid("p-1")],
                task_ids=[_tid("t-1")],
                costs={_pid("p-1"): {_tid("t-1"): float("inf")}},
                feasibility={_pid("p-1"): frozenset({_tid("t-1")})},
            )


# ---------------------------------------------------------------------------
# EF1 — the honest, external, independent verification (see module docstring)
# ---------------------------------------------------------------------------


def _bundles(result: FairAllocationResult, person_ids: Sequence[NodeId]) -> dict[NodeId, set[NodeId]]:
    bundles: dict[NodeId, set[NodeId]] = {p: set() for p in person_ids}
    for task_id, person_id in result.allocation.items():
        bundles[person_id].add(task_id)
    return bundles


def _assert_ef1_holds(
    result: FairAllocationResult,
    person_ids: Sequence[NodeId],
    costs: Mapping[NodeId, Mapping[NodeId, float]],
) -> None:
    """Delegates to `app.solvers.fair_allocation.verify_ef1` — the shared,
    production EF1-checking function (Phase 8, E2 addition) — rather than
    maintaining a second, local copy of the same check. `person_ids` is
    kept as a parameter for every call site's own readability even though
    `verify_ef1` itself derives the people to check from `result.order`."""
    del person_ids  # kept for call-site readability; verify_ef1 uses result.order
    violations = verify_ef1(result, costs)
    assert not violations, (
        f"EF1 violated: {violations[0].envier} envies {violations[0].envied} even after removing "
        f"{violations[0].envier}'s own most expensive item"
    )


class TestEF1ExternalVerification:
    """Four distinct, dense (every person priced every task) scenarios,
    each independently checked for EF1 by direct pairwise comparison —
    not by inspecting the solver's own internals."""

    def test_scenario_a_two_people_bounded_real_envy(self) -> None:
        person_ids = [_pid("p-1"), _pid("p-2")]
        task_ids = [_tid("t-1"), _tid("t-2"), _tid("t-3")]
        costs = {
            _pid("p-1"): {_tid("t-1"): 5.0, _tid("t-2"): 5.0, _tid("t-3"): 1.0},
            _pid("p-2"): {_tid("t-1"): 1.0, _tid("t-2"): 1.0, _tid("t-3"): 10.0},
        }
        feasibility = {p: frozenset(task_ids) for p in person_ids}
        result = solve_fair_allocation(
            person_ids=person_ids, task_ids=task_ids, costs=costs, feasibility=feasibility
        )
        # Worked by hand: p-1 takes t-3 (cost 1) then t-2 (cost 5) = 6 total;
        # p-2 takes t-1 (cost 1). p-1's own cost (6) exceeds p-1's cost for
        # p-2's bundle (5) — real envy — but is EF1 since removing p-1's own
        # worst item (t-2, cost 5) drops it to 1 <= 5.
        assert result.allocation == {
            _tid("t-3"): _pid("p-1"),
            _tid("t-1"): _pid("p-2"),
            _tid("t-2"): _pid("p-1"),
        }
        _assert_ef1_holds(result, person_ids, costs)

    def test_scenario_b_two_people_ties_and_bounded_envy(self) -> None:
        person_ids = [_pid("p-1"), _pid("p-2")]
        task_ids = [_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4")]
        costs = {
            _pid("p-1"): {_tid("t-1"): 3.0, _tid("t-2"): 3.0, _tid("t-3"): 3.0, _tid("t-4"): 3.0},
            _pid("p-2"): {_tid("t-1"): 1.0, _tid("t-2"): 2.0, _tid("t-3"): 8.0, _tid("t-4"): 9.0},
        }
        feasibility = {p: frozenset(task_ids) for p in person_ids}
        result = solve_fair_allocation(
            person_ids=person_ids, task_ids=task_ids, costs=costs, feasibility=feasibility
        )
        _assert_ef1_holds(result, person_ids, costs)

    def test_scenario_c_three_people_bounded_envy(self) -> None:
        person_ids = [_pid("p-1"), _pid("p-2"), _pid("p-3")]
        task_ids = [_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4"), _tid("t-5")]
        costs = {
            _pid("p-1"): _row(("t-1", 2.0), ("t-2", 6.0), ("t-3", 7.0), ("t-4", 1.0), ("t-5", 9.0)),
            _pid("p-2"): _row(("t-1", 8.0), ("t-2", 1.0), ("t-3", 2.0), ("t-4", 9.0), ("t-5", 3.0)),
            _pid("p-3"): _row(("t-1", 9.0), ("t-2", 9.0), ("t-3", 1.0), ("t-4", 8.0), ("t-5", 2.0)),
        }
        feasibility = {p: frozenset(task_ids) for p in person_ids}
        result = solve_fair_allocation(
            person_ids=person_ids, task_ids=task_ids, costs=costs, feasibility=feasibility
        )
        _assert_ef1_holds(result, person_ids, costs)

    def test_scenario_d_uneven_bundle_sizes_boundary_case(self) -> None:
        """Identical per-item costs for both people, 5 tasks over 2 people
        — one person necessarily gets 3 tasks, the other 2. This is the
        purest form of the 'up to one item' boundary: the equality case
        (envy exactly resolved, not merely bounded with room to spare)."""
        person_ids = [_pid("p-1"), _pid("p-2")]
        task_ids = [_tid("t-1"), _tid("t-2"), _tid("t-3"), _tid("t-4"), _tid("t-5")]
        costs = {
            _pid("p-1"): dict.fromkeys(task_ids, 1.0),
            _pid("p-2"): dict.fromkeys(task_ids, 1.0),
        }
        feasibility = {p: frozenset(task_ids) for p in person_ids}
        result = solve_fair_allocation(
            person_ids=person_ids, task_ids=task_ids, costs=costs, feasibility=feasibility
        )
        bundles = _bundles(result, person_ids)
        assert {len(bundles[p]) for p in person_ids} == {2, 3}
        _assert_ef1_holds(result, person_ids, costs)


def test_allocation_pick_and_result_are_frozen_dataclasses() -> None:
    """Sanity check on the shape E2's A17-A21 will consume: both are
    frozen (immutable) dataclasses, matching this codebase's domain-object
    convention."""
    pick = AllocationPick(turn_index=0, round_number=0, person_id=_pid("p-1"), task_id=_tid("t-1"), cost=1.0)
    with pytest.raises(AttributeError):
        pick.cost = 2.0  # type: ignore[misc]
