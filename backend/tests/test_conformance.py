"""Exercises the structural-conformance helper functions in
`app.graph.conformance`, `app.persistence.conformance`, and
`app.audit.conformance` at runtime too — `mypy --strict` is their primary
enforcement mechanism (see each module's own docstring), but calling them
also proves every constructor actually runs without error against a real
Firestore client, not just that the type annotations line up.
"""

from __future__ import annotations

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
from app.persistence.conformance import _idempotency_store_conforms
from app.persistence.firestore_store import FirestoreGraphStore


def test_all_graph_protocol_conformance_factories_construct(
    store: FirestoreGraphStore, firestore_client: firestore.Client
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
