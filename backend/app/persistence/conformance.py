"""Structural protocol conformance for `IdempotencyStore`, enforced by
`mypy --strict` (see `app.graph.conformance` for the graph-protocol
equivalents and the full rationale — protocols here are not
`@runtime_checkable`, so this function-returning-the-protocol-type pattern
is the structural stand-in for `isinstance` checks)."""

from __future__ import annotations

from contracts.repositories import IdempotencyStore
from google.cloud import firestore

from app.persistence.idempotency_store import FirestoreIdempotencyStore


def _idempotency_store_conforms(client: firestore.Client) -> IdempotencyStore:
    return FirestoreIdempotencyStore(client)
