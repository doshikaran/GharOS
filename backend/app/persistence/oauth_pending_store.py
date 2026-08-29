"""`OAuthPendingStore` — short-lived server-side state for an in-flight
OAuth Authorization-Code-plus-PKCE consent handshake (Phase 14.5,
ADR-023's OAuth ADR).

When E3's consent-start route redirects a household member to the
provider's consent screen, it mints a high-entropy CSRF `state` nonce and
must remember, for the ~seconds-to-minutes until the provider redirects
back to the callback route, two things it cannot put in the redirect URL:

- the PKCE `code_verifier` (the callback exchanges it, plus the returned
  `code`, for tokens), and
- an optional `principal_hint` (which connected-account identity the user
  was expecting to link, for a mismatch check after the real identity
  comes back in the token response).

This is not a graph concern and not a `contracts` Protocol — it is E1's
own persistence seam, the same status `RawPayloadStore` has. Records are:

- **single-use** — `take_pending` reads and deletes atomically in one
  transaction, so a replayed callback (or two racing callbacks) can never
  both consume the same `state`; and
- **short-lived** — a 10-minute TTL. `take_pending` treats an expired
  record as absent *and* deletes it (defense in depth, independent of any
  sweep). For bulk cleanup of records whose callback never arrived, two
  options, in preference order:

  1. **Production:** a Firestore native TTL policy on the `expire_at`
     field this store writes on every record. No code runs; Firestore
     deletes expired documents within ~24h of `expire_at`. The
     `take_pending` expiry check above is what keeps correctness tight
     in the window before that sweep lands.
  2. **Where a TTL policy is not configured** (the Firestore emulator has
     no TTL-policy surface): `sweep_expired()`, a `expire_at <= now`
     range-query delete, run from a periodic Cloud Scheduler ping or a
     startup hook. Provided here, fully implemented, for that case.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

import structlog
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.persistence.codecs.common import require_aware
from app.persistence.errors import OAuthPendingConflict

logger = structlog.get_logger(__name__)

_OAUTH_PENDING_COLLECTION = "oauth_pending"

PENDING_TTL = timedelta(minutes=10)
"""How long a minted `state` stays valid between consent-start and
callback. 10 minutes comfortably covers a human completing a provider
consent screen (including a fresh provider login / MFA) while keeping an
abandoned handshake's server-side footprint transient."""

_CODE_VERIFIER_FIELD = "code_verifier"
_PRINCIPAL_HINT_FIELD = "principal_hint"
_CREATED_AT_FIELD = "created_at"
_EXPIRE_AT_FIELD = "expire_at"


@dataclass(frozen=True, slots=True)
class OAuthPendingRecord:
    """One in-flight consent handshake's server-held state. Returned by
    `take_pending` exactly once, then gone."""

    code_verifier: str
    principal_hint: str | None
    created_at: datetime


class OAuthPendingStore(Protocol):
    """Structural interface for the pending-consent state store —
    E1-owned (not a `contracts` Protocol), matching `RawPayloadStore`'s
    status. `app.persistence.conformance` proves the Firestore
    implementation conforms under `mypy --strict`."""

    def put_pending(self, state: str, *, code_verifier: str, principal_hint: str | None) -> None:
        """Record the `code_verifier` / `principal_hint` for a freshly
        minted `state`. Raises `OAuthPendingConflict` if `state` is
        already recorded (a reused nonce or a replayed consent-start) —
        never overwrites an in-flight record."""
        ...

    def take_pending(self, state: str) -> OAuthPendingRecord | None:
        """Atomically read and delete the record for `state`. Returns
        `None` if `state` was never recorded, already consumed, or
        expired (an expired record is also deleted). Never returns the
        same record twice."""
        ...


class FirestoreOAuthPendingStore:
    """Structurally satisfies `OAuthPendingStore`.

    Constructed with an injected `firestore.Client`. `clock` is a test
    seam — it defaults to the real UTC wall clock and is only overridden
    in tests exercising TTL expiry; production always uses the default.
    """

    def __init__(
        self,
        client: firestore.Client,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._client = client
        self._clock: Callable[[], datetime] = clock if clock is not None else _utc_now

    def _collection(self) -> firestore.CollectionReference:
        return self._client.collection(_OAUTH_PENDING_COLLECTION)

    def put_pending(self, state: str, *, code_verifier: str, principal_hint: str | None) -> None:
        """See `OAuthPendingStore.put_pending`."""
        created_at = require_aware(self._clock(), field="created_at")
        doc_ref = self._collection().document(state)
        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> None:
            snapshot = doc_ref.get(transaction=txn)
            if snapshot.exists:
                raise OAuthPendingConflict(state=state)
            txn.set(
                doc_ref,
                {
                    "state": state,
                    _CODE_VERIFIER_FIELD: code_verifier,
                    _PRINCIPAL_HINT_FIELD: principal_hint,
                    _CREATED_AT_FIELD: created_at,
                    _EXPIRE_AT_FIELD: created_at + PENDING_TTL,
                },
            )

        _run(transaction)
        logger.info(
            "oauth_pending_store.put",
            state_prefix=state[:8],
            has_principal_hint=principal_hint is not None,
        )

    def take_pending(self, state: str) -> OAuthPendingRecord | None:
        """See `OAuthPendingStore.take_pending`."""
        now = require_aware(self._clock(), field="now")
        doc_ref = self._collection().document(state)
        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> tuple[OAuthPendingRecord | None, bool]:
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return None, False
            data = snapshot.to_dict() or {}
            txn.delete(doc_ref)  # single-use: consumed whether valid or expired
            expire_at = data.get(_EXPIRE_AT_FIELD)
            if expire_at is not None and now >= expire_at:
                return None, True
            record = OAuthPendingRecord(
                code_verifier=data[_CODE_VERIFIER_FIELD],
                principal_hint=data.get(_PRINCIPAL_HINT_FIELD),
                created_at=data[_CREATED_AT_FIELD],
            )
            return record, False

        outcome: tuple[OAuthPendingRecord | None, bool] = _run(transaction)
        record, was_expired = outcome
        if was_expired:
            logger.info("oauth_pending_store.take_expired", state_prefix=state[:8])
        elif record is None:
            logger.info("oauth_pending_store.take_miss", state_prefix=state[:8])
        return record

    def sweep_expired(self, *, now: datetime | None = None) -> int:
        """Delete every pending record whose `expire_at` is at or before
        `now` (default: the store's clock). Returns the number deleted.

        The fallback bulk-cleanup path for deployments without a Firestore
        native TTL policy on `expire_at` (see this module's docstring).
        Range query on a single field — Firestore auto-indexes it, so no
        `backend/migrations` entry is needed.
        """
        cutoff = require_aware(now if now is not None else self._clock(), field="now")
        query = self._collection().where(filter=FieldFilter(_EXPIRE_AT_FIELD, "<=", cutoff))
        deleted = 0
        for snap in query.stream():
            snap.reference.delete()
            deleted += 1
        if deleted:
            logger.info("oauth_pending_store.sweep_expired", deleted=deleted)
        return deleted


def _utc_now() -> datetime:
    return datetime.now(UTC)


def create_oauth_pending_store(client: firestore.Client) -> FirestoreOAuthPendingStore:
    """Composition-root factory — mirrors `create_oauth_credential_store`
    / `create_firestore_client`: dependency-injected, never a
    module-level singleton."""
    return FirestoreOAuthPendingStore(client)
