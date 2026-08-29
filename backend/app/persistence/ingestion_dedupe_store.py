"""`FirestoreIngestionDedupeStore` — real, durable backing for
`contracts.ingestion.IngestionDedupeStore` (Phase 14.5, ADR-023 §3).

The per-*document* idempotency index, keyed by
`contracts.ingestion.compute_content_hash`. It is the exact sibling of
`app.persistence.idempotency_store.FirestoreIdempotencyStore` (which keys
T3+ *tool* replays): this one keys *ingested documents*, so re-running the
same 24-hour mailbox scan a minute later writes zero new graph nodes —
every re-run outcome is `DUPLICATE_SKIPPED` (Gate 14.5).

ADR-023 §3 is explicit that this is an **operational index, not graph
traversal**: no `contracts.graph_types` field, no new node type, no new
`GraphReader` method. A small Firestore collection, one document per
content hash, is the whole mechanism.

The orchestrator is contractually required to call `seen()` before
running any stage for an item; `record()`'s create-if-not-exists
transaction is the backstop — a second `record()` for the same hash
raises `contracts.errors.IdempotencyConflict` rather than overwriting the
original SOURCE_DOCUMENT pointer.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog
from contracts.errors import IdempotencyConflict
from google.cloud import firestore

from app.persistence.codecs.common import require_aware

logger = structlog.get_logger(__name__)

_INGESTION_DEDUPE_COLLECTION = "ingestion_dedupe"

_SOURCE_DOCUMENT_ID_FIELD = "source_document_id"
_RUN_ID_FIELD = "run_id"
_INGESTED_AT_FIELD = "ingested_at"


class FirestoreIngestionDedupeStore:
    """Structurally satisfies `contracts.ingestion.IngestionDedupeStore`.

    Constructed with an injected `firestore.Client` — never a
    module-level singleton. Use `create_ingestion_dedupe_store` at the
    composition root.
    """

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def _collection(self) -> firestore.CollectionReference:
        return self._client.collection(_INGESTION_DEDUPE_COLLECTION)

    def seen(self, content_hash: str) -> str | None:
        """The SOURCE_DOCUMENT NodeId this `content_hash` was first
        ingested as, or `None` if it has never been seen. A single point
        read — called before any pipeline stage runs for an item."""
        snap = self._collection().document(content_hash).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        if data is None:
            return None
        recorded = data.get(_SOURCE_DOCUMENT_ID_FIELD)
        return None if recorded is None else str(recorded)

    def record(
        self,
        content_hash: str,
        *,
        source_document_id: str,
        run_id: str,
        ingested_at: datetime,
    ) -> None:
        """Record a first successful ingest — called exactly once per
        `INGESTED` outcome, after the graph write commits.

        A second `record()` for the same `content_hash` is a defect (the
        orchestrator is required to have checked `seen()` first): it
        raises `contracts.errors.IdempotencyConflict`, carrying the
        original SOURCE_DOCUMENT id as `original_result_ref`, rather than
        overwrite. Re-`record()`ing with the *same* `source_document_id`
        is likewise rejected — `record` means "first ingest", and a
        genuine replay should have been caught by `seen()`.
        """
        require_aware(ingested_at, field="ingested_at")
        doc_ref = self._collection().document(content_hash)
        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> None:
            snapshot = doc_ref.get(transaction=txn)
            if snapshot.exists:
                existing: dict[str, Any] = snapshot.to_dict() or {}
                original = str(existing.get(_SOURCE_DOCUMENT_ID_FIELD, ""))
                raise IdempotencyConflict(
                    idempotency_key=content_hash,
                    original_result_ref=original,
                )
            txn.set(
                doc_ref,
                {
                    "content_hash": content_hash,
                    _SOURCE_DOCUMENT_ID_FIELD: source_document_id,
                    _RUN_ID_FIELD: run_id,
                    _INGESTED_AT_FIELD: ingested_at,
                },
            )

        _run(transaction)
        logger.info(
            "ingestion_dedupe_store.record",
            content_hash=content_hash,
            source_document_id=source_document_id,
            run_id=run_id,
        )


def create_ingestion_dedupe_store(client: firestore.Client) -> FirestoreIngestionDedupeStore:
    """Composition-root factory — mirrors `create_oauth_credential_store`
    / `create_firestore_client`: dependency-injected, never a
    module-level singleton."""
    return FirestoreIngestionDedupeStore(client)
