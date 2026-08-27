"""Demo household seed loader (PHASES.md Phase 1 work item 8) — proves the
loader mechanism itself, independent of the individual traversal proofs in
`test_traversals.py`: every node/edge round-trips, `unexplained` is empty,
the integrity checker is clean, and the one supersession step actually
happened.
"""

from __future__ import annotations

from contracts.graph_types import Constraint, ConstraintSeverity, EdgeType, NodeId, Obligation

from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.collections import NODE_TYPE_TO_COLLECTION
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import SeedResult, build_demo_household
from seeds.seed_loader import load_demo_household


class TestSeedLoaderEndToEnd:
    def test_every_seeded_node_is_readable_after_loading(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        for node in seeded.nodes:
            readback = store.get_node(node.id)  # type: ignore[attr-defined]
            assert readback is not None, f"seeded node {node.id} not readable"  # type: ignore[attr-defined]

    def test_every_seeded_edge_is_readable_after_loading(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        all_edges = {e.id: e for e in store.all_edges()}
        for edge in seeded.edges:
            assert edge.id in all_edges

    def test_supersession_step_actually_happened(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        old_id, new_node = seeded.supersession
        old_current = store.get_node(old_id)
        assert isinstance(old_current, Obligation)
        assert old_current.provenance.superseded_at is not None

        new_current = store.get_node(new_node.id)
        assert isinstance(new_current, Obligation)
        assert new_current.provenance.superseded_at is None
        assert new_current.due_at is not None
        assert old_current.due_at is not None
        assert new_current.due_at > old_current.due_at

    def test_unexplained_is_empty_gate_1(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.unexplained(scope="all") == ()

    def test_integrity_checker_is_clean_gate_1(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert violations == (), violations

    def test_builder_is_pure_no_io(self) -> None:
        """`build_demo_household` performs no I/O — calling it twice
        produces structurally equal data both times."""
        first = build_demo_household()
        second = build_demo_household()
        assert len(first.nodes) == len(second.nodes)
        assert len(first.edges) == len(second.edges)
        assert {n.id for n in first.nodes} == {n.id for n in second.nodes}  # type: ignore[attr-defined]

    def test_covers_all_seventeen_node_types(self, seeded: SeedResult) -> None:
        seeded_types = {type(n) for n in seeded.nodes} | {type(seeded.supersession[1])}
        assert seeded_types == set(NODE_TYPE_TO_COLLECTION.keys())

    def test_covers_at_least_one_hard_constraint(self, seeded: SeedResult) -> None:
        hard_constraints = [
            n for n in seeded.nodes if isinstance(n, Constraint) and n.severity == ConstraintSeverity.HARD
        ]
        assert len(hard_constraints) >= 1

    def test_covers_the_seven_verification_edges(self, seeded: SeedResult) -> None:
        verification_edges = {
            EdgeType.LINE_ITEM_OF,
            EdgeType.DISCHARGES,
            EdgeType.VERIFIES,
            EdgeType.CONTRADICTS,
            EdgeType.ABSENT_FROM,
            EdgeType.SUBSTITUTES,
            EdgeType.EVIDENCES_EFFORT,
        }
        used_types = {e.edge_type for e in seeded.edges}
        assert verification_edges.issubset(used_types)


def test_load_demo_household_returns_the_same_seed_it_wrote(
    writer: FirestoreGraphWriter, store: FirestoreGraphStore
) -> None:
    seed = load_demo_household(writer)
    assert store.get_node(NodeId("person-priya")) is not None
    assert len(seed.nodes) > 0
