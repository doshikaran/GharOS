"""A11 Graph Maintainer (`app.graph.graph_maintainer`) — PHASES.md Phase
14, ADR-021 Decision 2.

Gate 14's own acceptance list, this module's share of it:
- **Protected node types provably never pruned** — the safety-critical
  piece: `assert_prunable`/`prune_if_eligible` raise `ProtectedNodeError`
  for `Decision`, `Outcome`, and HARD `Constraint` nodes, fail-closed
  (never a silent no-op that could be mistaken for success).
- Staleness detection, reusing `app.solvers.staleness.is_stale`, at
  graph-wide scope over real seeded `Obligation`s.
- Integrity-check invocation — delegates to (does not reimplement)
  `contracts.repositories.GraphIntegrityChecker`.
- Supersession — the maintainer's own call path onto the existing,
  already-correct `GraphWriter.supersede_node`.

Uses the real Firestore emulator for the staleness scan (needs a real
`FirestoreGraphStore.all_current_nodes` graph-wide scan) and simple fakes
for the integrity checker / graph writer (this module's own delegation to
each is the thing under test, not their own internal correctness, which
is already proven in `test_integrity_checker.py` / Phase 1's writer
tests).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Decision,
    DecisionStatus,
    Derivation,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Provenance,
    SourceRef,
)

from app.graph.graph_maintainer import GraphMaintainer, ProtectedNodeError, assert_prunable
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import SeedResult

from ._fake_graph_writer import FakeGraphWriter

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _provenance(*, derivation: Derivation = Derivation.EXTRACTED, created_at: datetime = _NOW) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=None if derivation is Derivation.AMBIGUOUS else SourceRef(NodeId("doc-1"), "p1"),
        confidence=0.9,
        deriving_agent=AgentId("A0"),
        created_at=created_at,
    )


def _decision(node_id: str) -> Decision:
    return Decision(
        id=NodeId(node_id),
        provenance=_provenance(),
        question="Should we relocate?",
        trigger="lease renewal notice",
        status=DecisionStatus.RESOLVED,
        resolution_summary="stay",
        rationale="cheaper",
    )


def _outcome(node_id: str) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=_provenance(derivation=Derivation.AMBIGUOUS),
        predicted="on time",
        actual="on time",
        variance=0.0,
        attribution_tags=("on-time",),
    )


def _constraint(node_id: str, *, severity: ConstraintSeverity) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=_provenance(),
        kind=ConstraintKind.DIETARY,
        severity=severity,
        validity_start=None,
        validity_end=None,
        structured={"allergen": "nut"},
        original_text="no nuts, ever",
    )


class _FakeIntegrityChecker:
    """Records the `scope` it was called with and returns a canned
    result — proves `GraphMaintainer.check_integrity` delegates rather
    than reimplementing orphan/provenance/dangling-edge detection."""

    def __init__(self, *, violations: tuple[str, ...] = ()) -> None:
        self._violations = violations
        self.check_calls: list[str] = []

    def check(self, scope: str) -> tuple[str, ...]:
        self.check_calls.append(scope)
        return self._violations


def _obligation(
    node_id: str,
    *,
    status: ObligationStatus = ObligationStatus.ASSIGNED,
    due_at: datetime | None,
    created_at: datetime = _NOW,
) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=_provenance(created_at=created_at),
        title=f"title-{node_id}",
        obligation_type="errand",
        due_at=due_at,
        must_start_by=None,
        effort_estimate_minutes=10,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


class TestProtectedNodesNeverPruned:
    """The safety-critical piece — fail-closed, structural, never a
    silent no-op."""

    def test_decision_raises(self) -> None:
        with pytest.raises(ProtectedNodeError):
            assert_prunable(_decision("decision-1"))

    def test_outcome_raises(self) -> None:
        with pytest.raises(ProtectedNodeError):
            assert_prunable(_outcome("outcome-1"))

    def test_hard_constraint_raises(self) -> None:
        with pytest.raises(ProtectedNodeError):
            assert_prunable(_constraint("constraint-1", severity=ConstraintSeverity.HARD))

    def test_soft_constraint_does_not_raise(self) -> None:
        assert_prunable(_constraint("constraint-2", severity=ConstraintSeverity.SOFT))  # must not raise

    def test_obligation_does_not_raise(self) -> None:
        assert_prunable(_obligation("obligation-1", due_at=None))  # must not raise

    def test_prune_if_eligible_raises_before_any_other_effect_for_decision(self) -> None:
        maintainer = GraphMaintainer(
            store=_unused_store(),
            integrity_checker=_FakeIntegrityChecker(),
            graph_writer=FakeGraphWriter(),
        )
        with pytest.raises(ProtectedNodeError):
            maintainer.prune_if_eligible(_decision("decision-2"))

    def test_prune_if_eligible_raises_for_outcome(self) -> None:
        maintainer = GraphMaintainer(
            store=_unused_store(),
            integrity_checker=_FakeIntegrityChecker(),
            graph_writer=FakeGraphWriter(),
        )
        with pytest.raises(ProtectedNodeError):
            maintainer.prune_if_eligible(_outcome("outcome-2"))

    def test_prune_if_eligible_raises_for_hard_constraint(self) -> None:
        maintainer = GraphMaintainer(
            store=_unused_store(),
            integrity_checker=_FakeIntegrityChecker(),
            graph_writer=FakeGraphWriter(),
        )
        with pytest.raises(ProtectedNodeError):
            maintainer.prune_if_eligible(_constraint("constraint-3", severity=ConstraintSeverity.HARD))

    def test_prune_if_eligible_never_deletes_anything_for_a_non_protected_node(self) -> None:
        """There is no delete primitive in this codebase at all (see
        `assert_prunable`'s docstring) — a non-protected node still
        results in `False` (nothing was actually pruned), never `True`."""
        maintainer = GraphMaintainer(
            store=_unused_store(),
            integrity_checker=_FakeIntegrityChecker(),
            graph_writer=FakeGraphWriter(),
        )
        result = maintainer.prune_if_eligible(_obligation("obligation-2", due_at=None))
        assert result is False


def _unused_store() -> FirestoreGraphStore:
    """`prune_if_eligible`/`assert_prunable` never touch the store — this
    stand-in documents that fact rather than requiring a real emulator
    connection for tests that don't need one. `object()` would fail
    `GraphMaintainer`'s own type checker at static-analysis time in a
    stricter setup; a real (but unused) `FirestoreGraphStore` reference
    would require a live client. Since `GraphMaintainer` never calls a
    method on `store` inside `prune_if_eligible`, any object satisfying
    nothing at runtime is safe here — but we still pass a minimal,
    honestly-typed placeholder rather than `None`, so a future change
    accidentally calling `self._store` inside this method fails loudly
    with an `AttributeError` instead of being silently tolerated."""

    class _Unused:
        pass

    return _Unused()  # type: ignore[return-value]


class TestSupersessionDelegation:
    def test_supersede_delegates_to_graph_writer(self) -> None:
        writer = FakeGraphWriter()
        maintainer = GraphMaintainer(
            store=_unused_store(), integrity_checker=_FakeIntegrityChecker(), graph_writer=writer
        )
        new_obligation = _obligation("obligation-v2", due_at=None)

        result = maintainer.supersede(NodeId("obligation-v1"), new_obligation)

        assert result == new_obligation.id
        assert writer.nodes[new_obligation.id] == new_obligation


class TestIntegrityCheckDelegation:
    def test_check_integrity_delegates_and_returns_violations_unchanged(self) -> None:
        checker = _FakeIntegrityChecker(violations=("node x: missing provenance",))
        maintainer = GraphMaintainer(
            store=_unused_store(), integrity_checker=checker, graph_writer=FakeGraphWriter()
        )

        violations = maintainer.check_integrity("all")

        assert violations == ("node x: missing provenance",)
        assert checker.check_calls == ["all"]


class TestStalenessDetectionAgainstRealGraph:
    """Graph-wide scan needs the real Firestore emulator (`store`
    fixture) — `all_current_nodes((Obligation,))` is exercised for real,
    not faked."""

    def test_stale_and_fresh_obligations_are_distinguished(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        # Overdue by 10 days, no status progression since -> stale.
        writer.write_node(
            _obligation(
                "obligation-overdue",
                due_at=_NOW - timedelta(days=10),
                created_at=_NOW - timedelta(days=10),
            )
        )
        # Due in the future -> not stale.
        writer.write_node(_obligation("obligation-future", due_at=_NOW + timedelta(days=5)))
        # Completed and overdue -> terminal status, never stale.
        writer.write_node(
            _obligation(
                "obligation-done",
                status=ObligationStatus.COMPLETED,
                due_at=_NOW - timedelta(days=30),
            )
        )
        checker = _FakeIntegrityChecker()
        maintainer = GraphMaintainer(store=store, integrity_checker=checker, graph_writer=writer)

        flags = maintainer.flagged_for_review(now=_NOW)

        flagged_ids = {flag.obligation_id for flag in flags}
        assert NodeId("obligation-overdue") in flagged_ids
        assert NodeId("obligation-future") not in flagged_ids
        assert NodeId("obligation-done") not in flagged_ids
        overdue_flag = next(f for f in flags if f.obligation_id == NodeId("obligation-overdue"))
        assert overdue_flag.days_stale == 10
        assert overdue_flag.threshold_days == 3

    def test_flags_are_sorted_deterministically(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(_obligation("obligation-z", due_at=_NOW - timedelta(days=20)))
        writer.write_node(_obligation("obligation-a", due_at=_NOW - timedelta(days=20)))
        maintainer = GraphMaintainer(
            store=store, integrity_checker=_FakeIntegrityChecker(), graph_writer=writer
        )

        flags = maintainer.flagged_for_review(now=_NOW)
        ids = [str(f.obligation_id) for f in flags]

        assert ids == sorted(ids)

    def test_run_returns_structured_result(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(_obligation("obligation-stale-run", due_at=_NOW - timedelta(days=15)))
        checker = _FakeIntegrityChecker(violations=("some violation",))
        maintainer = GraphMaintainer(store=store, integrity_checker=checker, graph_writer=writer)

        result = maintainer.run(now=_NOW)

        assert result.ran_at == _NOW
        assert any(f.obligation_id == NodeId("obligation-stale-run") for f in result.obligations_flagged)
        assert result.integrity_violations == ("some violation",)
        assert checker.check_calls == ["all"]


class TestFlaggedForReviewOnSeededDemoHousehold:
    """A real, current, honest scan over the actual seeded demo household
    — no obligation there is deliberately stale, so this proves the rule
    does not over-flag on real, well-formed data."""

    def test_no_false_positives_on_freshly_seeded_household(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        maintainer = GraphMaintainer(
            store=store,
            integrity_checker=_FakeIntegrityChecker(),
            graph_writer=FakeGraphWriter(),
        )
        # `seeds.demo_household.NOW` is the reference time the seed data
        # itself was authored against — evaluating staleness at that same
        # instant is the fair, like-for-like check.
        from seeds.demo_household import NOW as SEED_NOW

        flags = maintainer.flagged_for_review(now=SEED_NOW)

        # obligation-renew-prescription (o2) has a real future due_at
        # relative to SEED_NOW and is COMPLETED — not stale. Every other
        # seeded obligation is either COMPLETED/SUPERSEDED (terminal) or
        # has a near-future due_at. None should be flagged at seed time.
        assert flags == (), flags
