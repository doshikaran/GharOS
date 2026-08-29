"""Encode/decode codec for `contracts.ingestion.OAuthCredential` — the
`oauth_credentials` Firestore collection (Phase 14.5, ADR-023 §6).

Sits alongside `codecs/nodes.py` / `codecs/edges.py` (which translate
`contracts.graph_types` dataclasses) even though `OAuthCredential` is a
`contracts.ingestion` record, not a graph node: this package is the one
place a `contracts` dataclass is translated to and from a Firestore-safe
document dict, so a new persisted record shape gets its codec here rather
than hand-rolling `.value` / `tuple(...)` conversions inside the store.

**What is deliberately absent:** there is no field here for a refresh
token, an access token, an auth code, or a client secret — by design and
load-bearing (spec §23, `contracts.ingestion.OAuthCredential`'s own
docstring). The only credential-shaped string this codec ever writes is
`secret_ref`, a Secret Manager *resource name* pointer. Gate 14.5 proves
by test that no token-shaped material reaches this collection.
"""

from __future__ import annotations

from typing import Any

from contracts.ingestion import OAuthCredential, OAuthProvider

from app.persistence.codecs.common import encode_optional_datetime, require_aware

_FIELDS: tuple[str, ...] = (
    "provider",
    "principal",
    "granted_scopes",
    "secret_ref",
    "connected_at",
    "last_scan_at",
    "revoked_at",
)
"""The exact key set every `oauth_credentials` document carries — the
seven `OAuthCredential` fields and nothing else. `decode_oauth_credential`
reads only these; a Gate 14.5 test asserts a stored document's keys are
exactly this set (no stray token field ever crept in)."""


def encode_oauth_credential(credential: OAuthCredential) -> dict[str, Any]:
    """Translate an `OAuthCredential` to a Firestore document dict.

    Every datetime is enforced timezone-aware at this boundary
    (`require_aware`) — a naive `connected_at` is a caller bug, rejected
    here rather than silently stored as an ambiguous wall-clock, matching
    the graph write layer's discipline.
    """
    return {
        "provider": credential.provider.value,
        "principal": credential.principal,
        "granted_scopes": list(credential.granted_scopes),
        "secret_ref": credential.secret_ref,
        "connected_at": require_aware(credential.connected_at, field="connected_at"),
        "last_scan_at": encode_optional_datetime(credential.last_scan_at, field="last_scan_at"),
        "revoked_at": encode_optional_datetime(credential.revoked_at, field="revoked_at"),
    }


def decode_oauth_credential(data: dict[str, Any]) -> OAuthCredential:
    """Reconstruct an `OAuthCredential` from a Firestore document dict.

    Tolerant of a missing `last_scan_at` / `revoked_at` key (older
    documents, or a partial write) — both default to `None`, which is
    also their meaning ("never scanned" / "not revoked").
    """
    return OAuthCredential(
        provider=OAuthProvider(data["provider"]),
        principal=data["principal"],
        granted_scopes=tuple(data["granted_scopes"]),
        secret_ref=data["secret_ref"],
        connected_at=data["connected_at"],
        last_scan_at=data.get("last_scan_at"),
        revoked_at=data.get("revoked_at"),
    )
