"""Structural protocol conformance for `IdempotencyStore` and
`RawPayloadStore`, enforced by `mypy --strict` (see `app.graph.conformance`
for the graph-protocol equivalents and the full rationale — protocols here
are not `@runtime_checkable`, so this function-returning-the-protocol-type
pattern is the structural stand-in for `isinstance` checks).

`RawPayloadStore` is E1's own protocol (`raw_payload_store.py`), not a
`contracts.repositories` one — it is included here anyway since this is
the established location for "does this concrete class actually satisfy
this Protocol's shape" checks in `app.persistence`.
"""

from __future__ import annotations

from pathlib import Path

from contracts.repositories import IdempotencyStore
from google.cloud import firestore

from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.persistence.raw_payload_store import LocalFilesystemPayloadStore, RawPayloadStore


def _idempotency_store_conforms(client: firestore.Client) -> IdempotencyStore:
    return FirestoreIdempotencyStore(client)


def _raw_payload_store_conforms(storage_dir: Path) -> RawPayloadStore:
    return LocalFilesystemPayloadStore(storage_dir=storage_dir)
