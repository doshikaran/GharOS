"""Structural protocol conformance for `IdempotencyStore`,
`RawPayloadStore`, and the Phase 14.5 ingestion-connector stores
(`IngestionDedupeStore`, `OAuthCredentialStore`, plus E1's own
`OAuthPendingStore`), enforced by `mypy --strict` (see
`app.graph.conformance` for the graph-protocol equivalents and the full
rationale — protocols here are not `@runtime_checkable`, so this
function-returning-the-protocol-type pattern is the structural stand-in
for `isinstance` checks).

`RawPayloadStore` and `OAuthPendingStore` are E1's own protocols (defined
in `raw_payload_store.py` / `oauth_pending_store.py`), not
`contracts.repositories` / `contracts.ingestion` ones — they are included
here anyway since this is the established location for "does this concrete
class actually satisfy this Protocol's shape" checks in `app.persistence`.
"""

from __future__ import annotations

from pathlib import Path

from contracts.ingestion import IngestionDedupeStore, OAuthCredentialStore
from contracts.repositories import IdempotencyStore
from google.cloud import firestore

from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.persistence.ingestion_dedupe_store import FirestoreIngestionDedupeStore
from app.persistence.oauth_credential_store import FirestoreOAuthCredentialStore
from app.persistence.oauth_pending_store import FirestoreOAuthPendingStore, OAuthPendingStore
from app.persistence.raw_payload_store import LocalFilesystemPayloadStore, RawPayloadStore


def _idempotency_store_conforms(client: firestore.Client) -> IdempotencyStore:
    return FirestoreIdempotencyStore(client)


def _raw_payload_store_conforms(storage_dir: Path) -> RawPayloadStore:
    return LocalFilesystemPayloadStore(storage_dir=storage_dir)


def _ingestion_dedupe_store_conforms(client: firestore.Client) -> IngestionDedupeStore:
    return FirestoreIngestionDedupeStore(client)


def _oauth_credential_store_conforms(client: firestore.Client) -> OAuthCredentialStore:
    return FirestoreOAuthCredentialStore(client)


def _oauth_pending_store_conforms(client: firestore.Client) -> OAuthPendingStore:
    return FirestoreOAuthPendingStore(client)
