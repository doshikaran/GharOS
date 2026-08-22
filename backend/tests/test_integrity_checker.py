"""`FirestoreGraphIntegrityChecker` (spec §16.2) — orphans, missing
provenance, dangling edges. Gate 1: "integrity checker clean on seed
data."
"""

from __future__ import annotations

from contracts.graph_types import Edge, EdgeId, EdgeType, NodeId

from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import SeedResult
from tests.conftest import make_person, make_provenance


class TestCleanOnSeededData:
    def test_zero_violations_on_seeded_demo_household(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert violations == (), violations


class TestDanglingEdgeDetection:
    def test_dangling_from_id_is_detected(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(make_person("lonely-person", "Solo"))
        store.put_edge(
            Edge(
                id=EdgeId("edge-dangling-from"),
                provenance=make_provenance(),
                edge_type=EdgeType.OWNED_BY,
                from_id=NodeId("does-not-exist"),
                to_id=NodeId("lonely-person"),
            )
        )
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert any("does-not-exist" in v for v in violations)

    def test_dangling_to_id_is_detected(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(make_person("lonely-person-2", "Solo Two"))
        store.put_edge(
            Edge(
                id=EdgeId("edge-dangling-to"),
                provenance=make_provenance(),
                edge_type=EdgeType.OWNED_BY,
                from_id=NodeId("lonely-person-2"),
                to_id=NodeId("also-does-not-exist"),
            )
        )
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert any("also-does-not-exist" in v for v in violations)

    def test_absent_from_dangling_to_id_is_not_a_violation(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        """`absent_from`'s to_id is *expected* to never resolve — a
        SOURCE_DOCUMENT that never arrived is the whole point (spec §5.5),
        not corruption."""
        from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity

        constraint = Constraint(
            id=NodeId("constraint-x"),
            provenance=make_provenance(),
            kind=ConstraintKind.DIETARY,
            severity=ConstraintSeverity.HARD,
            validity_start=None,
            validity_end=None,
            structured={},
            original_text="no nuts",
        )
        writer.write_node(constraint)
        store.put_edge(
            Edge(
                id=EdgeId("edge-absent"),
                provenance=make_provenance(),
                edge_type=EdgeType.ABSENT_FROM,
                from_id=NodeId("constraint-x"),
                to_id=NodeId("some-doc-that-never-arrived"),
            )
        )
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        # constraint-x itself has an incident edge (not an orphan), and its
        # absent_from edge's dangling to_id must not appear as a violation
        assert not any("some-doc-that-never-arrived" in v for v in violations)


class TestOrphanDetection:
    def test_orphan_node_is_detected(self, store: FirestoreGraphStore, writer: FirestoreGraphWriter) -> None:
        writer.write_node(make_person("orphan-person", "Nobody links to me"))
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert any("orphan" in v and "orphan-person" in v for v in violations)

    def test_action_record_and_approval_request_are_not_flagged_as_orphans(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        """Documented contract gap (see `app.graph.integrity_checker`):
        neither node type has any edge type naming it as an endpoint in
        `contracts.graph_types.EdgeType`, so they are always edge-orphans
        by construction — special-cased out of this check rather than
        producing permanent false-positive noise."""
        from datetime import UTC, datetime

        from contracts.graph_types import ActionRecord, ApprovalRequest, ApprovalStatus

        writer.write_node(
            ActionRecord(
                id=NodeId("action-record-x"),
                provenance=make_provenance(),
                action_type="test_action",
                executed_at=datetime.now(UTC),
                approved_by=None,
            )
        )
        writer.write_node(
            ApprovalRequest(
                id=NodeId("approval-request-x"),
                provenance=make_provenance(),
                proposed_action_summary="test",
                evidence_bundle={},
                risk_tier="R2",
                confidence=0.8,
                consequence_if_wrong="none",
                status=ApprovalStatus.PENDING,
                expires_at=datetime.now(UTC),
            )
        )
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert not any("action-record-x" in v for v in violations)
        assert not any("approval-request-x" in v for v in violations)


class TestProvenanceViolationDetection:
    def test_directly_injected_bad_provenance_edge_is_detected(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        """Bypasses `FirestoreGraphWriter` entirely (raw client write) to
        simulate corrupted data — proves the checker re-validates
        independently of the write guard, exactly like `unexplained`."""
        writer.write_node(make_person("person-a", "A"))
        writer.write_node(make_person("person-b", "B"))
        store._client.collection("edges").document("bad-edge").set(  # noqa: SLF001
            {
                "id": "bad-edge",
                "provenance": None,
                "edge_type": "owned_by",
                "from_id": "person-a",
                "to_id": "person-b",
                "metadata": {},
            }
        )
        checker = FirestoreGraphIntegrityChecker(store)
        violations = checker.check(scope="all")
        assert any("bad-edge" in v and "missing provenance" in v for v in violations)
