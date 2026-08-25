"""HTTP-level tests for `app.api.graph_router`'s request/response
endpoints (`/graph/snapshot`, `/graph/nodes/{id}/justification`,
`/documents/{id}/raw`) — `/graph/stream` (SSE) is covered separately in
`test_graph_change_stream.py` (broadcaster-level) and
`test_graph_stream_endpoint.py` (HTTP-level SSE proof), since it needs a
different fixture shape (a long-lived connection, not a single
request/response).

Every route here is exercised through a real `fastapi.testclient.TestClient`
against `app.main.app`, with `get_graph_store` / `get_payload_store`
overridden to point at this test's isolated Firestore-emulator project and
a temp-directory payload store — the same real, provenance-guarded write
path (`writer`/`seeded` fixtures) every other Phase 1+ integration test in
this suite uses, never a mock repository.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from contracts.graph_types import NodeId, SourceDocument
from fastapi.testclient import TestClient

from app.api.graph_router import get_graph_store, get_payload_store
from app.graph.writer import FirestoreGraphWriter
from app.main import app
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.raw_payload_store import LocalFilesystemPayloadStore
from seeds.demo_household import SeedResult
from tests.conftest import NOW, make_provenance


@pytest.fixture
def payload_store(tmp_path: Path) -> LocalFilesystemPayloadStore:
    return LocalFilesystemPayloadStore(storage_dir=tmp_path / "payloads")


@pytest.fixture
def client(
    store: FirestoreGraphStore, payload_store: LocalFilesystemPayloadStore
) -> Iterator[TestClient]:
    """A `TestClient` wired to this test's own isolated emulator project —
    never the app's real lifespan-constructed client (see this module's
    docstring)."""
    app.dependency_overrides[get_graph_store] = lambda: store
    app.dependency_overrides[get_payload_store] = lambda: payload_store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestGraphSnapshot:
    def test_returns_seeded_nodes_and_edges(
        self, client: TestClient, seeded: SeedResult
    ) -> None:
        response = client.get("/graph/snapshot")
        assert response.status_code == 200
        body = response.json()

        nodes_by_id = {node["id"]: node for node in body["nodes"]}
        assert "person-priya" in nodes_by_id
        priya = nodes_by_id["person-priya"]
        assert priya["type"] == "PERSON"
        assert priya["label"] == "Priya"
        assert priya["derivation"] in {"extracted", "inferred", "ambiguous"}
        assert "display_name" in priya["fields"]
        assert "id" not in priya["fields"]
        assert "provenance" not in priya["fields"]
        assert "_version_seq" not in priya["fields"]

        obligation = nodes_by_id["obligation-pickup-aarav"]
        assert obligation["type"] == "OBLIGATION"
        assert obligation["label"] == "Pick up Aarav from school"
        assert obligation["source_document_id"] == "doc-school-whatsapp"

        # The one AMBIGUOUS/no-source-ref node in the seed data.
        pattern = nodes_by_id["pattern-priya-does-grocery-runs"]
        assert pattern["derivation"] == "ambiguous"
        assert pattern["source_document_id"] is None
        assert pattern["region"] is None

    def test_conflict_edges_are_flagged(self, client: TestClient, seeded: SeedResult) -> None:
        response = client.get("/graph/snapshot")
        body = response.json()
        edges_by_id = {edge["id"]: edge for edge in body["edges"]}

        conflicts_edge = edges_by_id["e-conflicts-o1-o4"]
        assert conflicts_edge["type"] == "conflicts_with"
        assert conflicts_edge["is_conflict"] is True

        violates_edge = edges_by_id["e-violates-o4-c2"]
        assert violates_edge["is_conflict"] is True

        non_conflict_edge = edges_by_id["e-states-pickup"]
        assert non_conflict_edge["type"] == "states"
        assert non_conflict_edge["is_conflict"] is False

    def test_node_count_matches_seed_data(self, client: TestClient, seeded: SeedResult) -> None:
        response = client.get("/graph/snapshot")
        body = response.json()
        # seeded.nodes is the original batch; the loader also writes one
        # supersession (a new current version replacing one of them), so
        # the current-node count equals len(seeded.nodes) exactly (one
        # node id gets superseded, one new id is added).
        assert len(body["nodes"]) == len(seeded.nodes) + 1


class TestGraphJustification:
    def test_known_node_returns_200_with_matching_root(
        self, client: TestClient, seeded: SeedResult
    ) -> None:
        response = client.get("/graph/nodes/obligation-renew-prescription/justification")
        assert response.status_code == 200
        body = response.json()
        assert body["root_node_id"] == "obligation-renew-prescription"
        assert body["steps"][0]["depth"] == 0
        assert body["steps"][0]["via_edge"] is None
        doc_ids = {doc["id"] for doc in body["source_documents"]}
        assert "doc-pharmacy-sms" in doc_ids

    def test_unknown_node_returns_404(self, client: TestClient, seeded: SeedResult) -> None:
        response = client.get("/graph/nodes/does-not-exist/justification")
        assert response.status_code == 404


class TestDocumentRaw:
    def test_resolves_and_returns_bytes_with_content_type(
        self,
        client: TestClient,
        writer: FirestoreGraphWriter,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        payload = b"hello from a real receipt image"
        raw_payload_ref = payload_store.store(payload, content_type="image/jpeg")
        doc = SourceDocument(
            id=NodeId("doc-raw-test"),
            provenance=make_provenance(),
            channel="upload",
            raw_payload_ref=raw_payload_ref,
            document_type="RECEIPT",
            ingested_at=NOW,
            original_language="en",
        )
        writer.write_node(doc)

        response = client.get("/documents/doc-raw-test/raw")
        assert response.status_code == 200
        assert response.content == payload
        assert response.headers["content-type"] == "image/jpeg"

    def test_unknown_document_id_returns_404(self, client: TestClient, seeded: SeedResult) -> None:
        response = client.get("/documents/does-not-exist/raw")
        assert response.status_code == 404

    def test_node_that_is_not_a_source_document_returns_404(
        self, client: TestClient, seeded: SeedResult
    ) -> None:
        response = client.get("/documents/person-priya/raw")
        assert response.status_code == 404
