"""Tests for `app.agents.consequence.context` — `gather_household_context`
and `assemble_implication_request`.

Real Firestore emulator (`reader`/`writer` fixtures) and a real
`LocalFilesystemPayloadStore` — no mocks, matching gharos-standards'
integration-test rule and `test_region_resolver.py`'s established pattern
for this exact combination.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from contracts.graph_types import (
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    SourceDocument,
)

from app.agents.consequence.context import assemble_implication_request, gather_household_context
from app.agents.consequence.errors import SourceDocumentNotResolvable
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.raw_payload_store import LocalFilesystemPayloadStore
from tests.conftest import NOW, make_person, make_provenance


def _write_source_document(
    writer: FirestoreGraphWriter, store: LocalFilesystemPayloadStore, *, node_id: str, text: str
) -> SourceDocument:
    ref = store.store(text.encode("utf-8"), content_type="text/plain")
    doc = SourceDocument(
        id=NodeId(node_id),
        provenance=make_provenance(),
        channel="email",
        raw_payload_ref=ref,
        document_type="school_communication",
        ingested_at=NOW,
        original_language=None,
    )
    writer.write_node(doc)
    return doc


def _obligation(
    node_id: str, title: str, *, status: ObligationStatus = ObligationStatus.ASSIGNED
) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=make_provenance(),
        title=title,
        obligation_type="errand",
        due_at=NOW,
        must_start_by=None,
        effort_estimate_minutes=15,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _constraint(node_id: str) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=make_provenance(),
        kind=ConstraintKind.DIETARY,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={"allergen": "nut"},
        original_text="No nuts, ever.",
    )


def _edge(edge_id: str, edge_type: EdgeType, from_id: NodeId, to_id: NodeId) -> Edge:
    return Edge(
        id=EdgeId(edge_id), provenance=make_provenance(), edge_type=edge_type, from_id=from_id, to_id=to_id
    )


class TestGatherHouseholdContext:
    def test_assembles_stated_open_people_and_constraints_within_reach(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, tmp_path: Path
    ) -> None:
        store = LocalFilesystemPayloadStore(storage_dir=tmp_path)
        doc = _write_source_document(writer, store, node_id="doc-ctx-1", text="Field trip Friday.")

        stated = _obligation("obl-ctx-stated", "Sign permission slip")
        writer.write_node(stated)
        writer.write_edge(_edge("e-ctx-states", EdgeType.STATES, doc.id, stated.id))

        open_obl = _obligation("obl-ctx-open", "Buy nut-free snacks")
        writer.write_node(open_obl)
        writer.write_edge(_edge("e-ctx-implies", EdgeType.IMPLIES, doc.id, open_obl.id))

        person = make_person("person-ctx-1", "Priya")
        writer.write_node(person)
        writer.write_edge(_edge("e-ctx-owned", EdgeType.OWNED_BY, open_obl.id, person.id))

        constraint = _constraint("constraint-ctx-1")
        writer.write_node(constraint)
        writer.write_edge(_edge("e-ctx-constrains", EdgeType.CONSTRAINS, constraint.id, person.id))

        closed = _obligation("obl-ctx-closed", "Already done", status=ObligationStatus.COMPLETED)
        writer.write_node(closed)
        writer.write_edge(_edge("e-ctx-closed-owned", EdgeType.OWNED_BY, closed.id, person.id))

        context = gather_household_context(reader, source_document_id=doc.id)

        assert {o.id for o in context.stated_obligations} == {stated.id}
        open_ids = {o.id for o in context.open_obligations}
        assert open_obl.id in open_ids
        assert stated.id not in open_ids
        assert closed.id not in open_ids  # closed-status obligations excluded
        assert {p.id for p in context.people} == {person.id}
        assert {c.id for c in context.constraints} == {constraint.id}

    def test_no_neighbours_returns_empty_context(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, tmp_path: Path
    ) -> None:
        store = LocalFilesystemPayloadStore(storage_dir=tmp_path)
        doc = _write_source_document(writer, store, node_id="doc-ctx-empty", text="Nothing else here.")

        context = gather_household_context(reader, source_document_id=doc.id)

        assert context.stated_obligations == ()
        assert context.open_obligations == ()
        assert context.people == ()
        assert context.constraints == ()


class TestAssembleImplicationRequest:
    def test_resolves_real_text_and_context_together(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, tmp_path: Path
    ) -> None:
        store = LocalFilesystemPayloadStore(storage_dir=tmp_path)
        text = "Field trip Friday. Signed permission slip due Wednesday."
        doc = _write_source_document(writer, store, node_id="doc-ctx-full", text=text)

        request = assemble_implication_request(reader, store, source_document_id=doc.id)

        assert request.source_document_id == doc.id
        assert request.document_text == text
        assert request.household_context.stated_obligations == ()

    def test_missing_source_document_raises(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, tmp_path: Path
    ) -> None:
        store = LocalFilesystemPayloadStore(storage_dir=tmp_path)
        with pytest.raises(SourceDocumentNotResolvable):
            assemble_implication_request(reader, store, source_document_id=NodeId("does-not-exist"))

    def test_non_utf8_payload_raises(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, tmp_path: Path
    ) -> None:
        store = LocalFilesystemPayloadStore(storage_dir=tmp_path)
        ref = store.store(b"\xff\xfe\x00\x01binary-not-utf8", content_type="image/png")
        doc = SourceDocument(
            id=NodeId("doc-ctx-binary"),
            provenance=make_provenance(),
            channel="email",
            raw_payload_ref=ref,
            document_type="receipt",
            ingested_at=datetime.now(UTC),
            original_language=None,
        )
        writer.write_node(doc)

        with pytest.raises(SourceDocumentNotResolvable):
            assemble_implication_request(reader, store, source_document_id=doc.id)
