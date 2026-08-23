"""Registry-gap logging — spec §5.4.3 rule 4: "Unknown type -> generic
extraction + human triage. Log it as a registry gap — this is how the
registry grows."

`contracts.errors.RegistryGap` is the typed exception the CTO already
froze for this failure mode; this module is the "genuinely retrievable,
not just printed" mechanism the operator's brief asks for, built around
it: raising `RegistryGap` interrupts the caller's control flow (nothing
proceeds silently on an unknown type), and `RegistryGapLog.record()`
durably records the fact it happened so the registry's actual growth
backlog is a queryable list, not a `logger.warning()` call that scrolls
off a terminal.

**Persistence scope, stated plainly:** this module's default store
(`InMemoryRegistryGapStore`) is process-lifetime only — real Cloud Run
retention of registry gaps across restarts is a small `registry_gaps`
Firestore collection, which is `backend/app/persistence/`, E1-owned
territory this phase does not touch. `RegistryGapStore` is a `Protocol`
specifically so that swap is a later, backwards-compatible drop-in: E1
implementing a `FirestoreRegistryGapStore` needs no change here or in any
caller of `RegistryGapLog`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

import structlog
from contracts.errors import RegistryGap

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class RegistryGapRecord:
    """One occurrence of the Intake Router (A2, E2) or an extractor (A3)
    hitting a document type not present in the Document-Type Registry."""

    type_id_attempted: str | None
    """The `type_id` the caller tried to resolve, if it had gotten that
    far — `None` for the fully-unclassifiable case (spec §5.4.3 rule 2:
    "if still ambiguous, escalate" — no single `type_id` was ever settled
    on)."""
    detection_summary: str
    """Human-readable summary of why this document didn't match — from
    `RegistryGap.detection_summary`, or supplied directly by the caller."""
    channel: str
    """Which ingestion channel this document arrived through (spec §17) —
    helps whoever triages the gap backlog spot channel-specific patterns
    (e.g. every gap arriving via `chat_export` suggests a chat-specific
    type the registry is missing)."""
    detection_signals_seen: tuple[str, ...]
    source_document_ref: str | None
    occurred_at: datetime

    def as_log_fields(self) -> dict[str, str]:
        """Flat string-valued view for structured logging — `structlog`
        renders keyword fields most usefully when they're already
        JSON-primitive-shaped, so this method does that conversion once
        rather than repeating it at every call site."""
        return {
            "type_id_attempted": self.type_id_attempted or "",
            "detection_summary": self.detection_summary,
            "channel": self.channel,
            "detection_signals_seen": ",".join(self.detection_signals_seen),
            "source_document_ref": self.source_document_ref or "",
            "occurred_at": self.occurred_at.isoformat(),
        }


class RegistryGapStore(Protocol):
    """Durable storage for `RegistryGapRecord`s — narrow enough that an
    in-memory list and a future Firestore collection both satisfy it with
    no adapter-of-an-adapter layer in between."""

    def append(self, record: RegistryGapRecord) -> None: ...

    def all_records(self) -> tuple[RegistryGapRecord, ...]: ...


@dataclass(slots=True)
class InMemoryRegistryGapStore:
    """Default `RegistryGapStore` — genuinely queryable within one
    process's lifetime (a running Cloud Run instance, a test), which is
    what "retrievable, not just printed" requires at this phase. See the
    module docstring for the Firestore-backed successor's scope.

    Not a module-level singleton (gharos-standards: "no module-level
    singletons holding I/O") — one instance is constructed at the
    composition root (or per test) and passed into `RegistryGapLog`.
    """

    _records: list[RegistryGapRecord] = field(default_factory=list)

    def append(self, record: RegistryGapRecord) -> None:
        self._records.append(record)

    def all_records(self) -> tuple[RegistryGapRecord, ...]:
        return tuple(self._records)


class RegistryGapLog:
    """The service E2's Intake Router (A2) calls when
    `DocumentTypeRegistry.resolve()` raises `RegistryGap`.

    Two effects, always both, in this order: a structured log line (for
    live observability — Cloud Logging in a real deployment) and a durable
    append to `store` (for the queryable backlog spec §5.4.3 rule 4 calls
    "how the registry grows"). Neither happens without the other — there
    is exactly one method that does both, so no caller can accidentally
    get one without the other.
    """

    def __init__(self, store: RegistryGapStore, *, clock: Callable[[], datetime] | None = None) -> None:
        """
        Args:
            store: durable backing store — `InMemoryRegistryGapStore()` in
                tests and early deployment; a Firestore-backed
                implementation once E1 builds one (see module docstring).
            clock: injected for deterministic tests; defaults to
                `datetime.now(UTC)`.
        """
        self._store = store
        self._clock = clock or (lambda: datetime.now(UTC))

    def record(
        self,
        *,
        type_id_attempted: str | None,
        detection_summary: str,
        channel: str,
        detection_signals_seen: tuple[str, ...] = (),
        source_document_ref: str | None = None,
    ) -> RegistryGapRecord:
        """Records one registry-gap occurrence. Never raises on its own
        behalf — recording a gap must not itself become a second failure
        on top of the one that produced it."""
        gap_record = RegistryGapRecord(
            type_id_attempted=type_id_attempted,
            detection_summary=detection_summary,
            channel=channel,
            detection_signals_seen=detection_signals_seen,
            source_document_ref=source_document_ref,
            occurred_at=self._clock(),
        )
        self._store.append(gap_record)
        logger.warning("registry_gap", **gap_record.as_log_fields())
        return gap_record

    def list_gaps(self) -> tuple[RegistryGapRecord, ...]:
        """The queryable backlog — "this is how the registry grows"
        (spec §5.4.3 rule 4): whoever decides what the *fifteenth*
        document type should be reads this, not a log archive."""
        return self._store.all_records()


def record_registry_gap(
    gap_log: RegistryGapLog,
    error: RegistryGap,
    *,
    channel: str,
    type_id_attempted: str | None = None,
    detection_signals_seen: tuple[str, ...] = (),
    source_document_ref: str | None = None,
) -> RegistryGapRecord:
    """Convenience wrapper for the common call shape: caller already caught
    a `RegistryGap` (typically from `DocumentTypeRegistry.resolve()`, see
    `document_registry.py`) and wants it recorded using the exception's own
    message as the detection summary, without re-typing that plumbing at
    every call site.
    """
    return gap_log.record(
        type_id_attempted=type_id_attempted,
        detection_summary=str(error),
        channel=channel,
        detection_signals_seen=detection_signals_seen,
        source_document_ref=source_document_ref,
    )


__all__ = [
    "InMemoryRegistryGapStore",
    "RegistryGapLog",
    "RegistryGapRecord",
    "RegistryGapStore",
    "record_registry_gap",
]
