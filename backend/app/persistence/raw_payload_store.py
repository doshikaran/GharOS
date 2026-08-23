"""`RawPayloadStore` — storage abstraction for SOURCE_DOCUMENT raw payload
content (PHASES.md Phase 3 work item: "source-document storage with region
references").

`contracts.graph_types.SourceDocument.raw_payload_ref` has existed since
Phase 1, but until this module nothing actually stored a raw document
payload (an email body, a photographed form's image bytes, a PDF) or
resolved that reference back to real content. Phase 6's graph
visualisation needs to click a node and see "the source document with the
region highlighted" — that only works if `raw_payload_ref` genuinely
resolves to bytes, not just an opaque string nobody can open.

**The swap point (architectural decision, not a hedge):** `RawPayloadStore`
is a structural `Protocol`, not a concrete class or ABC with required
inheritance. `LocalFilesystemPayloadStore` below is the first concrete
class satisfying it — a real, deliberate choice for local development and
the hackathon demo (no cloud dependency, no bucket to provision, trivial
to inspect on disk). A future `GCSPayloadStore` (real infra work, E3's
`infra/` territory to provision the bucket, for a later phase when this
is actually deployed) satisfies the exact same three-method shape —
`store`, `retrieve`, `content_type_of` — so every caller that is
constructed against `RawPayloadStore` (dependency-injected, per
gharos-standards' "no module-level singletons holding I/O" rule) needs
zero changes when that swap happens. Nothing about the Protocol assumes a
filesystem: `raw_payload_ref` is an opaque string to every caller, and its
internal shape (a `sha256:<hex digest>` content-address here) is a detail
private to whichever concrete store issued it — a `GCSPayloadStore` could
just as validly hand back `gs://bucket/sha256/<hex>` and nothing outside
this module would need to know.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Protocol

import structlog

from app.persistence.errors import RawPayloadNotFound
from app.settings import Settings

logger = structlog.get_logger(__name__)

_REF_SCHEME = "sha256:"
"""Prefix on every ref this store issues, disambiguating "a `sha256:`
content-address issued by `LocalFilesystemPayloadStore`" from whatever ref
shape a future concrete `RawPayloadStore` might issue — `retrieve`/
`content_type_of` reject any ref without this prefix as not-found rather
than guessing."""

_DIGEST_HEX_LENGTH = 64
"""`len(hashlib.sha256(b"").hexdigest())` — used to reject malformed refs
cheaply, before touching the filesystem."""

_PAYLOAD_SUFFIX = ".bin"
_META_SUFFIX = ".meta.json"
_META_CONTENT_TYPE_KEY = "content_type"
_META_SIZE_BYTES_KEY = "size_bytes"


class RawPayloadStore(Protocol):
    """Storage abstraction for SOURCE_DOCUMENT raw payload bytes.

    Structural (PEP 544) rather than an ABC, matching
    `contracts.repositories`'s protocol style — a concrete store need only
    satisfy this shape, never inherit from it. `app.persistence.conformance`
    proves `LocalFilesystemPayloadStore` conforms via `mypy --strict`
    (the same pattern used for every `contracts.repositories` protocol).
    """

    def store(self, payload: bytes, *, content_type: str) -> str:
        """Durably stores `payload`, returning a `raw_payload_ref` string
        usable as `SourceDocument.raw_payload_ref`. Storing the exact same
        bytes twice (even with different `content_type` — see
        `LocalFilesystemPayloadStore`'s docstring) returns the same ref
        rather than creating a duplicate."""
        ...

    def retrieve(self, raw_payload_ref: str) -> bytes:
        """Returns the exact bytes previously passed to `store` for this
        ref.

        Raises:
            RawPayloadNotFound: `raw_payload_ref` does not resolve to any
                stored payload. Never returns empty or garbage bytes.
        """
        ...

    def content_type_of(self, raw_payload_ref: str) -> str:
        """Returns the `content_type` passed to `store` for this ref —
        needed by any future renderer (Phase 6) deciding how to display a
        resolved region (an image crop vs. a text excerpt) without having
        to sniff the bytes itself.

        Raises:
            RawPayloadNotFound: `raw_payload_ref` does not resolve to any
                stored payload.
        """
        ...


class LocalFilesystemPayloadStore:
    """Local-filesystem-backed `RawPayloadStore` — the deliberate first
    implementation (see this module's docstring for the swap-point
    rationale), not a stand-in.

    **Content-addressed, not UUID-keyed.** The ref is `sha256:<hex digest
    of the payload bytes>`. This is a real design choice, not the only
    valid one: a random UUID would also satisfy the Protocol, but content-
    addressing gives store-time deduplication for free (storing the exact
    same receipt image twice — a genuinely common case, e.g. the same
    email attachment ingested via two channels — resolves to the same ref
    without this store having to notice or care), and it makes `store`
    naturally idempotent under retry (a crashed-and-retried `store` call
    for the same bytes reproduces the same ref rather than leaking a
    second copy).

    One consequence of hashing bytes only (not `content_type`): if the
    same bytes are ever stored under two different `content_type` values,
    the second `store` call is a no-op against the already-written
    payload — the *first* `content_type` recorded for that hash wins, and
    the mismatch is logged, never silently dropped or silently
    overwritten (overwriting stored metadata in place would violate the
    same "never silently correct" discipline the graph write layer
    enforces for provenance).

    Layout on disk, under `storage_dir`: a two-level shard directory from
    the digest's first two hex characters (`storage_dir/ab/ab34.../...`) —
    purely an operational nicety, keeping any single directory from
    accumulating an unbounded flat file count at real household-document
    volume — followed by `<digest>.bin` (the raw bytes) and
    `<digest>.meta.json` (`{"content_type": ..., "size_bytes": ...}`).
    """

    def __init__(self, *, storage_dir: Path) -> None:
        self._storage_dir = storage_dir
        self._storage_dir.mkdir(parents=True, exist_ok=True)

    def store(self, payload: bytes, *, content_type: str) -> str:
        """See `RawPayloadStore.store`. Computes the sha256 digest of
        `payload`, writes `<digest>.bin` and `<digest>.meta.json` if they
        do not already exist (dedup — see class docstring), and returns
        `sha256:<digest>`."""
        digest = hashlib.sha256(payload).hexdigest()
        raw_payload_ref = f"{_REF_SCHEME}{digest}"
        payload_path, meta_path = self._paths_for_digest(digest)

        if payload_path.is_file():
            self._warn_on_content_type_mismatch(
                meta_path, raw_payload_ref=raw_payload_ref, new_content_type=content_type
            )
            logger.debug(
                "raw_payload_store.dedup_hit",
                raw_payload_ref=raw_payload_ref,
                size_bytes=len(payload),
            )
            return raw_payload_ref

        payload_path.parent.mkdir(parents=True, exist_ok=True)
        # Write-to-temp-then-atomic-rename so a crash mid-write can never
        # leave a partially-written payload file behind under the final
        # name (POSIX `Path.replace` is atomic within the same filesystem).
        tmp_payload_path = payload_path.with_name(payload_path.name + ".tmp")
        tmp_payload_path.write_bytes(payload)
        tmp_payload_path.replace(payload_path)

        meta = {_META_CONTENT_TYPE_KEY: content_type, _META_SIZE_BYTES_KEY: len(payload)}
        tmp_meta_path = meta_path.with_name(meta_path.name + ".tmp")
        tmp_meta_path.write_text(json.dumps(meta), encoding="utf-8")
        tmp_meta_path.replace(meta_path)

        logger.info(
            "raw_payload_store.stored",
            raw_payload_ref=raw_payload_ref,
            content_type=content_type,
            size_bytes=len(payload),
        )
        return raw_payload_ref

    def retrieve(self, raw_payload_ref: str) -> bytes:
        """See `RawPayloadStore.retrieve`."""
        digest = self._digest_from_ref(raw_payload_ref)
        payload_path, _ = self._paths_for_digest(digest)
        if not payload_path.is_file():
            raise RawPayloadNotFound(raw_payload_ref=raw_payload_ref)
        return payload_path.read_bytes()

    def content_type_of(self, raw_payload_ref: str) -> str:
        """See `RawPayloadStore.content_type_of`."""
        digest = self._digest_from_ref(raw_payload_ref)
        _, meta_path = self._paths_for_digest(digest)
        if not meta_path.is_file():
            raise RawPayloadNotFound(raw_payload_ref=raw_payload_ref)
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        return str(meta[_META_CONTENT_TYPE_KEY])

    def _digest_from_ref(self, raw_payload_ref: str) -> str:
        """Extracts and validates the hex digest from a `sha256:...` ref.

        Raises:
            RawPayloadNotFound: `raw_payload_ref` is not a well-formed ref
                issued by this store — a malformed ref can never resolve,
                so this is folded into the same not-found error rather
                than a separate error type.
        """
        if not raw_payload_ref.startswith(_REF_SCHEME):
            raise RawPayloadNotFound(raw_payload_ref=raw_payload_ref)
        digest = raw_payload_ref[len(_REF_SCHEME) :]
        if len(digest) != _DIGEST_HEX_LENGTH or not all(c in "0123456789abcdef" for c in digest.lower()):
            raise RawPayloadNotFound(raw_payload_ref=raw_payload_ref)
        return digest.lower()

    def _paths_for_digest(self, digest: str) -> tuple[Path, Path]:
        shard_dir = self._storage_dir / digest[:2]
        return (
            shard_dir / f"{digest}{_PAYLOAD_SUFFIX}",
            shard_dir / f"{digest}{_META_SUFFIX}",
        )

    def _warn_on_content_type_mismatch(
        self, meta_path: Path, *, raw_payload_ref: str, new_content_type: str
    ) -> None:
        if not meta_path.is_file():
            return
        existing_meta = json.loads(meta_path.read_text(encoding="utf-8"))
        existing_content_type = existing_meta.get(_META_CONTENT_TYPE_KEY)
        if existing_content_type != new_content_type:
            logger.warning(
                "raw_payload_store.content_type_mismatch_on_dedup",
                raw_payload_ref=raw_payload_ref,
                existing_content_type=existing_content_type,
                ignored_content_type=new_content_type,
            )


def create_local_filesystem_payload_store(settings: Settings) -> LocalFilesystemPayloadStore:
    """Builds a `LocalFilesystemPayloadStore` from typed settings —
    mirrors `firestore_client.create_firestore_client`'s pattern:
    dependency-injected at the composition root, never a module-level
    singleton."""
    return LocalFilesystemPayloadStore(storage_dir=Path(settings.raw_payload_storage_dir))
