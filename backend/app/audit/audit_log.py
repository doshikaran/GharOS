"""`FirestoreAuditLog` — real, durable, append-only backing for
`contracts.repositories.AuditLog` (L6, spec §6.2).

Append-only by construction: nothing in this class offers an update or
delete path. Each call to `append` writes exactly one new immutable
document; there is no method that could overwrite or remove one. This is
what `write_before_execute` relies on to make "audit before execute"
(safety invariant #2) a durability guarantee, not just an ordering
convention.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.cloud import firestore

_AUDIT_COLLECTION = "audit_log"


@dataclass(frozen=True, slots=True)
class AuditRecord:
    """One durable, immutable audit entry."""

    id: str
    action_type: str
    payload: dict[str, str]
    occurred_at: datetime
    written_at: datetime


class FirestoreAuditLog:
    """Structurally satisfies `contracts.repositories.AuditLog`."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def append(self, *, action_type: str, payload: dict[str, str], occurred_at: datetime) -> str:
        """Durably writes one immutable audit record and returns its id.

        Per the protocol's docstring, the caller MUST call this — and
        observe it complete — strictly before the corresponding action
        executes. `write_before_execute` (this package) is the sanctioned
        way to guarantee that ordering structurally rather than by
        caller discipline.
        """
        record_id = str(uuid.uuid4())
        written_at = datetime.now(UTC)
        doc_ref = self._client.collection(_AUDIT_COLLECTION).document(record_id)
        doc_ref.set(
            {
                "id": record_id,
                "action_type": action_type,
                "payload": dict(payload),
                "occurred_at": occurred_at,
                "written_at": written_at,
            }
        )
        return record_id

    def get(self, record_id: str) -> AuditRecord | None:
        """Not part of the frozen `AuditLog` protocol — an extra read path
        this class exposes for tests and observability, since `append`
        only returns an opaque id."""
        snap = self._client.collection(_AUDIT_COLLECTION).document(record_id).get()
        if not snap.exists:
            return None
        data: dict[str, Any] | None = snap.to_dict()
        if data is None:
            return None
        return AuditRecord(
            id=data["id"],
            action_type=data["action_type"],
            payload=dict(data["payload"]),
            occurred_at=data["occurred_at"],
            written_at=data["written_at"],
        )

    def all_records(self) -> tuple[AuditRecord, ...]:
        """Not part of the frozen `AuditLog` protocol — exposed for tests
        and the future audit-review UI (E4)."""
        records: list[AuditRecord] = []
        for snap in self._client.collection(_AUDIT_COLLECTION).stream():
            data = snap.to_dict()
            if data is None:
                continue
            records.append(
                AuditRecord(
                    id=data["id"],
                    action_type=data["action_type"],
                    payload=dict(data["payload"]),
                    occurred_at=data["occurred_at"],
                    written_at=data["written_at"],
                )
            )
        return tuple(records)
