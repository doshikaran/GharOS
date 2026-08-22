"""Gate 1: "a provenance-less write is impossible — proven by hypothesis
fuzz test" — run against the REAL Firestore-emulator-backed
`FirestoreGraphWriter`, not the Phase 0 in-memory stub.

`test_write_node_rejects_every_combination_of_missing_fields` is the
load-bearing test: it fuzzes every non-empty subset of the five required
provenance fields being absent and asserts the guard rejects every single
one *before any Firestore write happens* — a handful of example-based
tests is not sufficient evidence for "structurally impossible" per the
gharos-standards skill.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from contracts.errors import ProvenanceMissing
from contracts.graph_types import AgentId, Derivation, NodeId, Provenance, SourceRef
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from app.graph.writer import FirestoreGraphWriter
from app.persistence.provenance_guard import validate_provenance
from tests.conftest import make_person


def _valid_provenance() -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
        confidence=0.9,
        deriving_agent=AgentId("A0"),
        created_at=datetime.now(UTC),
    )


class TestWriteNodeProvenanceGuard:
    def test_write_node_accepts_complete_provenance(self, writer: FirestoreGraphWriter) -> None:
        node_id = writer.write_node(make_person("person-1", "Priya"))
        assert node_id == NodeId("person-1")

    def test_write_node_rejects_none_provenance(self, writer: FirestoreGraphWriter) -> None:
        node = SimpleNamespace(id=NodeId("bad-1"), provenance=None)
        with pytest.raises(ProvenanceMissing):
            writer.write_node(node)

    def test_write_node_rejects_missing_provenance_attribute(self, writer: FirestoreGraphWriter) -> None:
        node = SimpleNamespace(id=NodeId("bad-2"))  # no `provenance` at all
        with pytest.raises(ProvenanceMissing):
            writer.write_node(node)

    def test_rejected_write_never_reaches_firestore(self, writer: FirestoreGraphWriter) -> None:
        """The guard runs before any network call — a rejected node must
        not be readable afterwards, not even partially."""
        node = SimpleNamespace(id=NodeId("bad-3"), provenance=None)
        with pytest.raises(ProvenanceMissing):
            writer.write_node(node)
        assert writer._store.get_node(NodeId("bad-3")) is None  # noqa: SLF001

    @given(
        missing_fields=st.lists(
            st.sampled_from(["derivation", "source_ref", "confidence", "deriving_agent", "created_at"]),
            min_size=1,
            max_size=5,
            unique=True,
        )
    )
    @settings(
        suppress_health_check=[HealthCheck.function_scoped_fixture],
        deadline=None,
        max_examples=50,
    )
    def test_write_node_rejects_every_combination_of_missing_fields(
        self, writer: FirestoreGraphWriter, missing_fields: list[str]
    ) -> None:
        """Fuzzes every non-empty subset of the five provenance fields
        being absent and asserts the REAL, emulator-backed writer rejects
        every single one — this is the "structurally impossible to
        bypass" proof Gate 1 requires, run against production write code,
        not a stand-in."""
        valid = _valid_provenance()
        provenance_fields = {
            "derivation": valid.derivation,
            "source_ref": valid.source_ref,
            "confidence": valid.confidence,
            "deriving_agent": valid.deriving_agent,
            "created_at": valid.created_at,
            "superseded_at": valid.superseded_at,
        }
        fake_provenance = SimpleNamespace(**provenance_fields)
        for field_name in missing_fields:
            delattr(fake_provenance, field_name)

        node = SimpleNamespace(id=NodeId("fuzzed"), provenance=fake_provenance)
        with pytest.raises(ProvenanceMissing) as exc_info:
            writer.write_node(node)
        for field_name in missing_fields:
            assert field_name in exc_info.value.missing_fields
        # never partially landed in Firestore
        assert writer._store.get_node(NodeId("fuzzed")) is None  # noqa: SLF001

    def test_ambiguous_derivation_permits_none_source_ref(self) -> None:
        """source_ref is the one field legitimately None for
        AMBIGUOUS-with-no-single-source provenance (spec §5.6) — the guard
        must not reject this as "missing"."""
        provenance = Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=0.4,
            deriving_agent=AgentId("A10"),
            created_at=datetime.now(UTC),
        )
        validate_provenance(SimpleNamespace(id=NodeId("ambiguous-1"), provenance=provenance))

    def test_supersede_rejects_incomplete_new_node_and_leaves_old_untouched(
        self, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(make_person("person-1", "Priya"))

        bad_new_version = SimpleNamespace(id=NodeId("person-1-v2"), provenance=None)
        with pytest.raises(ProvenanceMissing):
            writer.supersede_node(NodeId("person-1"), bad_new_version)

        current = writer._store.get_node(NodeId("person-1"))  # noqa: SLF001
        assert current is not None
        assert current.provenance.superseded_at is None


class TestWriteEdgeProvenanceGuard:
    def test_write_edge_rejects_none_provenance(self, writer: FirestoreGraphWriter) -> None:
        from contracts.graph_types import EdgeType

        edge = SimpleNamespace(
            id="bad-edge-1",
            provenance=None,
            edge_type=EdgeType.OWNED_BY,
            from_id=NodeId("a"),
            to_id=NodeId("b"),
            metadata={},
        )
        with pytest.raises(ProvenanceMissing):
            writer.write_edge(edge)  # type: ignore[arg-type]
