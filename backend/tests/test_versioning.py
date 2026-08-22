"""PHASES.md Phase 1 work item 3 — versioning and supersession, against
the real Firestore-emulator-backed store: writes create versions;
`superseded_at` is set once and never overwritten; the prior version is
never deleted and stays readable.
"""

from __future__ import annotations

from dataclasses import replace

import pytest
from contracts.errors import ProvenanceMissing
from contracts.graph_types import NodeId

from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from tests.conftest import make_person


class TestPutNodeCreatesVersions:
    def test_writing_the_same_id_twice_keeps_both_versions_in_history(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        v1 = make_person("person-1", "Priya")
        writer.write_node(v1)
        v2 = replace(v1, display_name="Priya Sharma")
        writer.write_node(v2)

        current = store.get_node(NodeId("person-1"))
        assert current is not None
        assert current.display_name == "Priya Sharma"

        history = store.node_history(NodeId("person-1"))
        assert len(history) == 2
        assert history[0].display_name == "Priya"
        assert history[1].display_name == "Priya Sharma"

    def test_node_history_is_empty_for_a_never_written_id(self, store: FirestoreGraphStore) -> None:
        assert store.node_history(NodeId("never-written")) == ()


class TestSupersedeNode:
    def test_supersede_marks_old_version_and_writes_new_current(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        old = make_person("person-1", "Priya")
        writer.write_node(old)

        new = make_person("person-1-v2", "Priya Sharma (verified)")
        returned_id = writer.supersede_node(NodeId("person-1"), new)
        assert returned_id == NodeId("person-1-v2")

        old_current = store.get_node(NodeId("person-1"))
        assert old_current is not None
        assert old_current.provenance.superseded_at is not None

        new_current = store.get_node(NodeId("person-1-v2"))
        assert new_current is not None
        assert new_current.provenance.superseded_at is None
        assert new_current.display_name == "Priya Sharma (verified)"

    def test_old_version_is_never_deleted_still_readable_via_history(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        old = make_person("person-1", "Priya")
        writer.write_node(old)
        new = make_person("person-1-v2", "Priya Sharma")
        writer.supersede_node(NodeId("person-1"), new)

        history = store.node_history(NodeId("person-1"))
        # first entry: the pristine original write (superseded_at None)
        assert history[0].provenance.superseded_at is None
        # a later entry records the moment it became superseded
        assert any(v.provenance.superseded_at is not None for v in history)
        # the original content values are still intact in history
        assert history[0].display_name == "Priya"

    def test_superseded_at_is_never_overwritten_by_a_second_supersession(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        old = make_person("person-1", "Priya")
        writer.write_node(old)
        new_a = make_person("person-1-v2", "Priya A")
        writer.supersede_node(NodeId("person-1"), new_a)
        first_superseded_at = store.get_node(NodeId("person-1")).provenance.superseded_at  # type: ignore[union-attr]

        # a second, unrelated supersession naming the same old id again —
        # must not push `superseded_at` forward a second time.
        new_b = make_person("person-1-v3", "Priya B")
        writer.supersede_node(NodeId("person-1"), new_b)
        second_superseded_at = store.get_node(NodeId("person-1")).provenance.superseded_at  # type: ignore[union-attr]

        assert first_superseded_at == second_superseded_at

    def test_supersede_of_never_written_id_still_writes_new_node(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        """No old version exists — supersede_node degrades gracefully to a
        plain write of the new node (nothing to mark superseded)."""
        new = make_person("person-new", "Nobody Before Me")
        writer.supersede_node(NodeId("does-not-exist"), new)
        assert store.get_node(NodeId("person-new")) is not None
        assert store.get_node(NodeId("does-not-exist")) is None

    def test_supersede_rejects_incomplete_new_node_before_touching_old(
        self, store: FirestoreGraphStore, writer: FirestoreGraphWriter
    ) -> None:
        from types import SimpleNamespace

        old = make_person("person-1", "Priya")
        writer.write_node(old)

        bad_new = SimpleNamespace(id=NodeId("person-1-v2"), provenance=None)
        with pytest.raises(ProvenanceMissing):
            writer.supersede_node(NodeId("person-1"), bad_new)

        # old version completely untouched by the rejected supersession
        current = store.get_node(NodeId("person-1"))
        assert current is not None
        assert current.provenance.superseded_at is None
        assert store.get_node(NodeId("person-1-v2")) is None
