"""Exercises the structural-conformance helper functions in
`app.graph.conformance`, `app.persistence.conformance`, and
`app.audit.conformance` at runtime too — `mypy --strict` is their primary
enforcement mechanism (see each module's own docstring), but calling them
also proves every constructor actually runs without error against a real
Firestore client, not just that the type annotations line up.
"""

from __future__ import annotations

from pathlib import Path

from google.cloud import firestore

from app.audit.conformance import _audit_log_conforms
from app.graph.conformance import (
    _decision_repository_conforms,
    _graph_integrity_checker_conforms,
    _graph_reader_conforms,
    _graph_writer_conforms,
    _obligation_repository_conforms,
    _pattern_repository_conforms,
    _person_repository_conforms,
)
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.conformance import (
    _idempotency_store_conforms,
    _ingestion_dedupe_store_conforms,
    _oauth_credential_store_conforms,
    _oauth_pending_store_conforms,
    _raw_payload_store_conforms,
)
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.tools.conformance import (
    _graph_read_tool_conforms_to_read_only_tool,
    _graph_read_tool_conforms_to_tool,
    _graph_write_tool_conforms,
)


def test_all_graph_protocol_conformance_factories_construct(
    store: FirestoreGraphStore, firestore_client: firestore.Client, tmp_path: Path
) -> None:
    assert _graph_reader_conforms(store) is not None
    assert _graph_writer_conforms(store) is not None
    assert _person_repository_conforms(store) is not None
    assert _obligation_repository_conforms(store) is not None
    assert _decision_repository_conforms(store) is not None
    assert _pattern_repository_conforms(store) is not None
    assert _graph_integrity_checker_conforms(store) is not None
    assert _audit_log_conforms(firestore_client) is not None
    assert _idempotency_store_conforms(firestore_client) is not None
    assert _raw_payload_store_conforms(tmp_path / "raw_payloads") is not None
    assert _ingestion_dedupe_store_conforms(firestore_client) is not None
    assert _oauth_credential_store_conforms(firestore_client) is not None
    assert _oauth_pending_store_conforms(firestore_client) is not None


def test_all_tool_protocol_conformance_factories_construct(
    reader: FirestoreGraphReader, writer: FirestoreGraphWriter, idempotency_store: FirestoreIdempotencyStore
) -> None:
    assert _graph_read_tool_conforms_to_tool(reader) is not None
    assert _graph_read_tool_conforms_to_read_only_tool(reader) is not None
    assert _graph_write_tool_conforms(writer, idempotency_store) is not None
