"""Tests for `app.solvers.fair_allocation.verify_ef1` (Phase 8, E2
addition) — the shared EF1-checking function `test_fair_allocation.py`'s
own `TestEF1ExternalVerification` now delegates to (see that module's
updated docstring) and that A19 (Fairness Verifier/Explainer) calls in
production.

These tests focus on `verify_ef1`'s own contract beyond what
`test_fair_allocation.py`'s scenario tests already cover end-to-end: a
genuine violation is reported with the right numbers, and incomplete cost
coverage raises rather than silently passing.
"""

from __future__ import annotations

import pytest
from contracts.graph_types import NodeId

from app.solvers.fair_allocation import (
    AllocationPick,
    FairAllocationResult,
    IncompleteCostCoverageError,
    verify_ef1,
)


def _pid(raw: str) -> NodeId:
    return NodeId(raw)


def _tid(raw: str) -> NodeId:
    return NodeId(raw)


def _result(*, order: tuple[NodeId, ...], allocation: dict[NodeId, NodeId]) -> FairAllocationResult:
    """A minimal, hand-built `FairAllocationResult` — `verify_ef1` only
    reads `.order` and `.allocation`, so `picks`/`person_total_cost` are
    irrelevant filler for these tests."""
    return FairAllocationResult(allocation=allocation, picks=(), person_total_cost={}, order=order)


class TestNoViolations:
    def test_empty_bundle_never_envies(self) -> None:
        """A person with an empty bundle cannot violate EF1 against
        anyone — nothing to remove, no own cost to compare."""
        result = _result(order=(_pid("p-1"), _pid("p-2")), allocation={_tid("t-1"): _pid("p-1")})
        costs = {_pid("p-1"): {_tid("t-1"): 5.0}, _pid("p-2"): {_tid("t-1"): 5.0}}

        violations = verify_ef1(result, costs)

        assert violations == ()

    def test_dense_fair_split_has_no_violations(self) -> None:
        result = _result(
            order=(_pid("p-1"), _pid("p-2")),
            allocation={_tid("t-1"): _pid("p-1"), _tid("t-2"): _pid("p-2")},
        )
        costs = {
            _pid("p-1"): {_tid("t-1"): 1.0, _tid("t-2"): 1.0},
            _pid("p-2"): {_tid("t-1"): 1.0, _tid("t-2"): 1.0},
        }

        assert verify_ef1(result, costs) == ()


class TestRealViolationDetected:
    def test_genuine_envy_beyond_one_item_is_reported_with_real_numbers(self) -> None:
        """p-1 gets two costly tasks, p-2 gets one cheap task, and even
        removing p-1's own worst item leaves p-1 envying p-2 — a real,
        reportable EF1 violation (not the bounded-envy case Scenario A in
        `test_fair_allocation.py` exercises)."""
        result = _result(
            order=(_pid("p-1"), _pid("p-2")),
            allocation={_tid("t-1"): _pid("p-1"), _tid("t-2"): _pid("p-1"), _tid("t-3"): _pid("p-2")},
        )
        costs = {
            _pid("p-1"): {_tid("t-1"): 10.0, _tid("t-2"): 10.0, _tid("t-3"): 1.0},
            _pid("p-2"): {_tid("t-1"): 10.0, _tid("t-2"): 10.0, _tid("t-3"): 1.0},
        }

        violations = verify_ef1(result, costs)

        assert len(violations) == 1
        violation = violations[0]
        assert violation.envier == _pid("p-1")
        assert violation.envied == _pid("p-2")
        assert violation.envier_own_bundle_cost == 20.0
        assert violation.envier_worst_own_item_cost == 10.0
        assert violation.envier_cost_for_envied_bundle == 1.0
        # 20.0 - 10.0 = 10.0 > 1.0 -> genuine violation


class TestIncompleteCostCoverage:
    def test_missing_cost_for_own_bundle_task_raises(self) -> None:
        result = _result(order=(_pid("p-1"), _pid("p-2")), allocation={_tid("t-1"): _pid("p-1")})
        costs: dict[NodeId, dict[NodeId, float]] = {_pid("p-1"): {}, _pid("p-2"): {}}

        with pytest.raises(IncompleteCostCoverageError) as exc_info:
            verify_ef1(result, costs)

        assert exc_info.value.envier == _pid("p-1")
        assert exc_info.value.missing_task_id == _tid("t-1")

    def test_missing_cost_for_envied_bundle_task_raises(self) -> None:
        result = _result(
            order=(_pid("p-1"), _pid("p-2")),
            allocation={_tid("t-1"): _pid("p-1"), _tid("t-2"): _pid("p-2")},
        )
        # p-1 has an entry for their own task, but never priced p-2's task.
        costs = {_pid("p-1"): {_tid("t-1"): 5.0}, _pid("p-2"): {_tid("t-2"): 3.0}}

        with pytest.raises(IncompleteCostCoverageError) as exc_info:
            verify_ef1(result, costs)

        assert exc_info.value.envier == _pid("p-1")
        assert exc_info.value.envied == _pid("p-2")
        assert exc_info.value.missing_task_id == _tid("t-2")


def test_never_duplicates_round_robin_construction_logic() -> None:
    """`verify_ef1` must never *call* the solver's own construction path —
    a structural guarantee that this is genuinely an external check, not
    a tautological one that would agree with a broken solver by
    construction. Checked via the compiled function's own `co_names` (the
    real names it references at runtime), not a raw text search over its
    source — a raw search would false-positive on this function's own
    docstring, which *names* `_round_robin_pass` to explain that it is
    never called."""
    referenced_names = verify_ef1.__code__.co_names
    assert "_round_robin_pass" not in referenced_names
    assert "solve_fair_allocation" not in referenced_names


def test_allocation_pick_import_unused_marker() -> None:
    """Sanity: `AllocationPick` remains importable from this module for
    any test that wants to hand-construct a `FairAllocationResult.picks`
    entry — not exercised by the tests above, which use an empty tuple."""
    pick = AllocationPick(turn_index=0, round_number=0, person_id=_pid("p-1"), task_id=_tid("t-1"), cost=1.0)
    assert pick.cost == 1.0
