"""`LocalFilesystemPayloadStore` (PHASES.md Phase 3 work item:
"source-document storage with region references") — round-trip fidelity,
content-addressed dedup, and the typed not-found error for refs that do
not resolve.

Pure filesystem I/O, no Firestore emulator needed — uses pytest's
`tmp_path` for full test isolation, same spirit as `conftest.py`'s
per-test-random-project Firestore isolation.
"""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.persistence.errors import RawPayloadNotFound
from app.persistence.raw_payload_store import (
    LocalFilesystemPayloadStore,
    create_local_filesystem_payload_store,
)
from app.settings import Settings


@pytest.fixture
def store(tmp_path: Path) -> LocalFilesystemPayloadStore:
    return LocalFilesystemPayloadStore(storage_dir=tmp_path / "raw_payloads")


class TestStoreRetrieveRoundTrip:
    @pytest.mark.parametrize(
        ("payload", "content_type"),
        [
            (b"", "text/plain"),
            (b"a", "text/plain"),
            (b"Dear parents, the field trip is on Tuesday.", "text/plain"),
            (b"\x00\x01\x02\xff\xfe" * 1000, "application/octet-stream"),
            (bytes(range(256)) * 4096, "image/jpeg"),  # ~1MB binary
        ],
        ids=["empty", "single_byte", "email_body", "small_binary", "large_binary_1mb"],
    )
    def test_round_trips_exactly(
        self, store: LocalFilesystemPayloadStore, payload: bytes, content_type: str
    ) -> None:
        ref = store.store(payload, content_type=content_type)
        assert store.retrieve(ref) == payload
        assert store.content_type_of(ref) == content_type

    @given(payload=st.binary(min_size=0, max_size=5000))
    def test_round_trips_for_arbitrary_bytes(self, payload: bytes) -> None:
        # A real TemporaryDirectory per hypothesis example (not pytest's
        # function-scoped `tmp_path`, which hypothesis warns is not reset
        # between generated inputs) — a fresh store per example so dedup
        # across examples never masks a genuine round-trip bug.
        with tempfile.TemporaryDirectory() as tmp_dir:
            fuzz_store = LocalFilesystemPayloadStore(storage_dir=Path(tmp_dir))
            ref = fuzz_store.store(payload, content_type="application/octet-stream")
            assert fuzz_store.retrieve(ref) == payload

    def test_ref_is_content_addressed_sha256(self, store: LocalFilesystemPayloadStore) -> None:
        payload = b"receipt contents"
        ref = store.store(payload, content_type="text/plain")
        assert ref == f"sha256:{hashlib.sha256(payload).hexdigest()}"


class TestContentAddressedDedup:
    def test_storing_identical_payload_twice_returns_the_same_ref(
        self, store: LocalFilesystemPayloadStore
    ) -> None:
        payload = b"the exact same email attachment, ingested via two channels"
        ref_1 = store.store(payload, content_type="text/plain")
        ref_2 = store.store(payload, content_type="text/plain")
        assert ref_1 == ref_2

    def test_storing_identical_payload_twice_does_not_duplicate_on_disk(
        self, tmp_path: Path
    ) -> None:
        storage_dir = tmp_path / "raw_payloads"
        store = LocalFilesystemPayloadStore(storage_dir=storage_dir)
        payload = b"duplicate me"
        store.store(payload, content_type="text/plain")
        store.store(payload, content_type="text/plain")
        payload_files = list(storage_dir.rglob("*.bin"))
        assert len(payload_files) == 1

    def test_different_payloads_get_different_refs(self, store: LocalFilesystemPayloadStore) -> None:
        ref_a = store.store(b"payload A", content_type="text/plain")
        ref_b = store.store(b"payload B", content_type="text/plain")
        assert ref_a != ref_b

    def test_dedup_hit_keeps_the_first_content_type(self, store: LocalFilesystemPayloadStore) -> None:
        payload = b"same bytes, conflicting content-type claims"
        ref_1 = store.store(payload, content_type="text/plain")
        ref_2 = store.store(payload, content_type="application/pdf")
        assert ref_1 == ref_2
        assert store.content_type_of(ref_1) == "text/plain"


class TestRetrieveNonexistentRefRaises:
    def test_well_formed_but_never_stored_ref_raises(self, store: LocalFilesystemPayloadStore) -> None:
        never_stored_ref = f"sha256:{'0' * 64}"
        with pytest.raises(RawPayloadNotFound):
            store.retrieve(never_stored_ref)

    def test_malformed_ref_wrong_scheme_raises(self, store: LocalFilesystemPayloadStore) -> None:
        with pytest.raises(RawPayloadNotFound):
            store.retrieve("gs://some-bucket/object")

    def test_malformed_ref_wrong_length_raises(self, store: LocalFilesystemPayloadStore) -> None:
        with pytest.raises(RawPayloadNotFound):
            store.retrieve("sha256:deadbeef")

    def test_malformed_ref_non_hex_raises(self, store: LocalFilesystemPayloadStore) -> None:
        with pytest.raises(RawPayloadNotFound):
            store.retrieve("sha256:" + ("z" * 64))

    def test_retrieve_never_returns_empty_bytes_for_a_missing_ref(
        self, store: LocalFilesystemPayloadStore
    ) -> None:
        # Guard against a regression that silently returns b"" instead of
        # raising — b"" is itself a legitimate stored payload (see the
        # "empty" round-trip case above), so "not found" must never be
        # conflated with "found and empty".
        never_stored_ref = f"sha256:{'f' * 64}"
        with pytest.raises(RawPayloadNotFound) as exc_info:
            store.retrieve(never_stored_ref)
        assert exc_info.value.raw_payload_ref == never_stored_ref

    def test_content_type_of_nonexistent_ref_raises(self, store: LocalFilesystemPayloadStore) -> None:
        with pytest.raises(RawPayloadNotFound):
            store.content_type_of(f"sha256:{'a' * 64}")


class TestPersistenceAcrossInstances:
    """A restarted process (a fresh `LocalFilesystemPayloadStore` instance)
    pointed at the same durable directory must see everything a prior
    instance stored — mirrors the crash-recovery style proof in
    `test_idempotency_store.py`."""

    def test_second_store_instance_sees_payloads_stored_by_the_first(self, tmp_path: Path) -> None:
        storage_dir = tmp_path / "raw_payloads"
        store_process_1 = LocalFilesystemPayloadStore(storage_dir=storage_dir)
        ref = store_process_1.store(b"survives a restart", content_type="text/plain")

        store_process_2 = LocalFilesystemPayloadStore(storage_dir=storage_dir)
        assert store_process_2.retrieve(ref) == b"survives a restart"
        assert store_process_2.content_type_of(ref) == "text/plain"


class TestFactoryFromSettings:
    def test_create_local_filesystem_payload_store_uses_settings_dir(self, tmp_path: Path) -> None:
        settings = Settings(raw_payload_storage_dir=str(tmp_path / "from-settings"))
        store = create_local_filesystem_payload_store(settings)
        ref = store.store(b"hello", content_type="text/plain")
        assert store.retrieve(ref) == b"hello"
        assert (tmp_path / "from-settings").is_dir()
