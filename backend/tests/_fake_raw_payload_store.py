"""An in-memory `app.persistence.raw_payload_store.RawPayloadStore` test
double — for unit tests (Phase 13 voice-subsystem tests) that need a real
object satisfying the `RawPayloadStore` Protocol without touching the
filesystem.

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_fake_idempotency_store.py`'s established pattern.
"""

from __future__ import annotations

import hashlib

from app.persistence.errors import RawPayloadNotFound

_REF_SCHEME = "sha256:"


class FakeRawPayloadStore:
    """Structurally satisfies `app.persistence.raw_payload_store.
    RawPayloadStore` — content-addressed, in-memory, matching
    `LocalFilesystemPayloadStore`'s own dedup-by-content-hash semantics
    without touching disk."""

    def __init__(self) -> None:
        self._payloads: dict[str, bytes] = {}
        self._content_types: dict[str, str] = {}
        self.store_calls = 0

    def store(self, payload: bytes, *, content_type: str) -> str:
        self.store_calls += 1
        digest = hashlib.sha256(payload).hexdigest()
        ref = f"{_REF_SCHEME}{digest}"
        if ref not in self._payloads:
            self._payloads[ref] = payload
            self._content_types[ref] = content_type
        return ref

    def retrieve(self, raw_payload_ref: str) -> bytes:
        if raw_payload_ref not in self._payloads:
            raise RawPayloadNotFound(raw_payload_ref=raw_payload_ref)
        return self._payloads[raw_payload_ref]

    def content_type_of(self, raw_payload_ref: str) -> str:
        if raw_payload_ref not in self._content_types:
            raise RawPayloadNotFound(raw_payload_ref=raw_payload_ref)
        return self._content_types[raw_payload_ref]


__all__ = ["FakeRawPayloadStore"]
