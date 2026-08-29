"""`FirestoreIngestionDedupeStore` (Phase 14.5, ADR-023 §3) against the
real Firestore emulator.

Proves: `seen()` misses to `None`; after `record()` it returns the
originating SOURCE_DOCUMENT id; a second `record()` for the same
`compute_content_hash` raises `contracts.errors.IdempotencyConflict`
(the create-if-not-exists backstop behind the orchestrator's
seen()-first contract); and the index is durable across a process
restart (a fresh store instance on the same Firestore project still
dedupes), mirroring `test_idempotency_store.py`'s crash-recovery proof.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.errors import IdempotencyConflict
from contracts.ingestion import IngestionSourceKind, compute_content_hash
from google.cloud import firestore

from app.persistence.codecs.common import NaiveDatetimeError
from app.persistence.conformance import _ingestion_dedupe_store_conforms
from app.persistence.ingestion_dedupe_store import (
    FirestoreIngestionDedupeStore,
    create_ingestion_dedupe_store,
)

INGESTED_AT = datetime(2026, 8, 29, 14, 0, tzinfo=UTC)


def _hash(*, external_identity: str = "gmail-msg-1", text: str = "school picnic on Friday") -> str:
    return compute_content_hash(
        source_kind=IngestionSourceKind.GMAIL,
        external_identity=external_identity,
        media_type="text/plain",
        raw_bytes=None,
        text_content=text,
    )


@pytest.fixture
def dedupe_store(firestore_client: firestore.Client) -> FirestoreIngestionDedupeStore:
    return create_ingestion_dedupe_store(firestore_client)


class TestConformance:
    def test_conformance_factory_constructs(self, firestore_client: firestore.Client) -> None:
        assert _ingestion_dedupe_store_conforms(firestore_client) is not None


class TestSeenAndRecord:
    def test_seen_miss_returns_none(self, dedupe_store: FirestoreIngestionDedupeStore) -> None:
        assert dedupe_store.seen(_hash()) is None

    def test_record_then_seen_returns_source_document_id(
        self, dedupe_store: FirestoreIngestionDedupeStore
    ) -> None:
        content_hash = _hash()
        dedupe_store.record(
            content_hash,
            source_document_id="src-doc-42",
            run_id="run-1",
            ingested_at=INGESTED_AT,
        )
        assert dedupe_store.seen(content_hash) == "src-doc-42"

    def test_distinct_hashes_are_independent(self, dedupe_store: FirestoreIngestionDedupeStore) -> None:
        dedupe_store.record(
            _hash(external_identity="msg-a"),
            source_document_id="src-a",
            run_id="run-1",
            ingested_at=INGESTED_AT,
        )
        assert dedupe_store.seen(_hash(external_identity="msg-b")) is None

    def test_naive_ingested_at_is_rejected(self, dedupe_store: FirestoreIngestionDedupeStore) -> None:
        with pytest.raises(NaiveDatetimeError):
            dedupe_store.record(
                _hash(),
                source_document_id="src-doc-1",
                run_id="run-1",
                ingested_at=datetime(2026, 8, 29, 14, 0),
            )


class TestSecondRecordConflicts:
    def test_second_record_same_hash_raises_idempotency_conflict(
        self, dedupe_store: FirestoreIngestionDedupeStore
    ) -> None:
        content_hash = _hash()
        dedupe_store.record(
            content_hash,
            source_document_id="src-doc-1",
            run_id="run-1",
            ingested_at=INGESTED_AT,
        )
        with pytest.raises(IdempotencyConflict) as excinfo:
            dedupe_store.record(
                content_hash,
                source_document_id="src-doc-2",
                run_id="run-2",
                ingested_at=INGESTED_AT,
            )
        assert excinfo.value.idempotency_key == content_hash
        assert excinfo.value.original_result_ref == "src-doc-1"
        # the original pointer is untouched
        assert dedupe_store.seen(content_hash) == "src-doc-1"

    def test_re_record_with_identical_source_document_id_still_conflicts(
        self, dedupe_store: FirestoreIngestionDedupeStore
    ) -> None:
        content_hash = _hash()
        dedupe_store.record(
            content_hash,
            source_document_id="src-doc-1",
            run_id="run-1",
            ingested_at=INGESTED_AT,
        )
        with pytest.raises(IdempotencyConflict):
            dedupe_store.record(
                content_hash,
                source_document_id="src-doc-1",
                run_id="run-1",
                ingested_at=INGESTED_AT,
            )


class TestDurabilityAcrossRestart:
    """A re-scan of the same window by a restarted process must still
    write zero new nodes — the dedupe index is in durable Firestore, not
    process memory (Gate 14.5, mirroring the idempotency store's
    crash-recovery test)."""

    def test_fresh_store_instance_same_project_still_dedupes(
        self, firestore_client: firestore.Client
    ) -> None:
        content_hash = _hash()

        store_1 = FirestoreIngestionDedupeStore(firestore_client)
        store_1.record(
            content_hash,
            source_document_id="src-doc-1",
            run_id="run-1",
            ingested_at=INGESTED_AT,
        )

        store_2 = FirestoreIngestionDedupeStore(firestore_client)
        assert store_2.seen(content_hash) == "src-doc-1"
        with pytest.raises(IdempotencyConflict):
            store_2.record(
                content_hash,
                source_document_id="src-doc-1",
                run_id="run-2",
                ingested_at=INGESTED_AT,
            )
