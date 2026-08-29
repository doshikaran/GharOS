"""`FirestoreOAuthCredentialStore` — real, durable backing for
`contracts.ingestion.OAuthCredentialStore` (Phase 14.5, ADR-023 §6;
spec §17, §23).

One connected account = one Firestore document in the `oauth_credentials`
collection, keyed by `OAuthCredential.storage_key`
(`f"{provider.value}:{principal}"`). The document holds **only** the seven
`OAuthCredential` fields (`app.persistence.codecs.oauth._FIELDS`) — never
a refresh token, an access token, an auth code, or a client secret. The
refresh token lives solely in Secret Manager at the resource named by the
stored `secret_ref` string; access tokens are exchanged in memory for one
connector run and never persisted. Nothing a reasoning agent can reach —
this collection included — ever carries token material (Gate 14.5 proves
this by test).

`mark_revoked` is a soft delete: `revoked_at` is set exactly once and
never cleared or overwritten, matching this project's supersession
discipline (a revoked row is retained for the audit trail and shown as
"disconnected" in the Connections UI). `list_active` filters revoked rows
out with a single-field equality query (`revoked_at == None`) — Firestore
auto-indexes single fields, so this needs no `backend/migrations`
composite-index entry.
"""

from __future__ import annotations

from datetime import datetime

import structlog
from contracts.ingestion import OAuthCredential, OAuthProvider
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.persistence.codecs.common import require_aware
from app.persistence.codecs.oauth import decode_oauth_credential, encode_oauth_credential
from app.persistence.errors import OAuthCredentialNotFound

logger = structlog.get_logger(__name__)

_OAUTH_CREDENTIALS_COLLECTION = "oauth_credentials"

_REVOKED_AT_FIELD = "revoked_at"
_LAST_SCAN_AT_FIELD = "last_scan_at"


def _storage_key(provider: OAuthProvider, principal: str) -> str:
    """The Firestore document id for a `(provider, principal)` pair —
    identical to `OAuthCredential.storage_key`, defined here too so the
    read/mutate methods (which take the pair, not a whole record) key the
    same way `put` does."""
    return f"{provider.value}:{principal}"


class FirestoreOAuthCredentialStore:
    """Structurally satisfies `contracts.ingestion.OAuthCredentialStore`.

    Constructed with an injected `firestore.Client` — never a
    module-level singleton (gharos-standards dependency-injection rule).
    Use `create_oauth_credential_store` at the composition root.
    """

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    def _collection(self) -> firestore.CollectionReference:
        return self._client.collection(_OAUTH_CREDENTIALS_COLLECTION)

    def get(self, provider: OAuthProvider, principal: str) -> OAuthCredential | None:
        """Return the stored credential for `(provider, principal)`, or
        `None` if none was ever stored. A revoked credential is still
        returned here (its `is_active` is `False`) — only `list_active`
        filters revoked rows out."""
        snap = self._collection().document(_storage_key(provider, principal)).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        return None if data is None else decode_oauth_credential(data)

    def list_active(self) -> tuple[OAuthCredential, ...]:
        """Every credential with `revoked_at is None`, via a single-field
        equality query so a large revoked-row history never has to be
        streamed and filtered in process."""
        query = self._collection().where(filter=FieldFilter(_REVOKED_AT_FIELD, "==", None))
        return tuple(
            decode_oauth_credential(data) for snap in query.stream() if (data := snap.to_dict()) is not None
        )

    def put(self, credential: OAuthCredential) -> None:
        """Insert or replace the row for `(credential.provider,
        credential.principal)`. Called by the OAuth callback route after a
        successful consent exchange. A full `set` (not `update`) so a
        re-consent cleanly replaces a prior — possibly revoked — row for
        the same account with a fresh grant."""
        doc_ref = self._collection().document(credential.storage_key)
        doc_ref.set(encode_oauth_credential(credential))
        logger.info(
            "oauth_credential_store.put",
            provider=credential.provider.value,
            principal=credential.principal,
            granted_scopes=list(credential.granted_scopes),
            secret_ref=credential.secret_ref,
            revoked=not credential.is_active,
        )

    def mark_revoked(self, provider: OAuthProvider, principal: str, *, revoked_at: datetime) -> None:
        """Soft-delete: set `revoked_at` once. A second call for an
        already-revoked row is a harmless no-op — the first revocation
        timestamp wins and is never overwritten. Raises
        `OAuthCredentialNotFound` if there is no row to revoke (never
        creates one).

        The caller remains separately responsible for destroying the
        Secret Manager version the row's `secret_ref` names.
        """
        require_aware(revoked_at, field="revoked_at")
        doc_ref = self._collection().document(_storage_key(provider, principal))
        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> bool:
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return False
            data = snapshot.to_dict() or {}
            if data.get(_REVOKED_AT_FIELD) is not None:
                return True  # already revoked — leave the original timestamp
            txn.update(doc_ref, {_REVOKED_AT_FIELD: revoked_at})
            return True

        existed: bool = _run(transaction)
        if not existed:
            raise OAuthCredentialNotFound(provider=provider.value, principal=principal)
        logger.info(
            "oauth_credential_store.mark_revoked",
            provider=provider.value,
            principal=principal,
        )

    def touch_last_scan(self, provider: OAuthProvider, principal: str, *, at: datetime) -> None:
        """Update `last_scan_at` after a connector run, and nothing else.
        Raises `OAuthCredentialNotFound` if there is no row (never creates
        one). Permitted on a revoked row — a late in-flight scan
        completing after disconnect still records honestly when it ran."""
        require_aware(at, field="last_scan_at")
        doc_ref = self._collection().document(_storage_key(provider, principal))
        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> bool:
            snapshot = doc_ref.get(transaction=txn)
            if not snapshot.exists:
                return False
            txn.update(doc_ref, {_LAST_SCAN_AT_FIELD: at})
            return True

        existed: bool = _run(transaction)
        if not existed:
            raise OAuthCredentialNotFound(provider=provider.value, principal=principal)


def create_oauth_credential_store(client: firestore.Client) -> FirestoreOAuthCredentialStore:
    """Composition-root factory — mirrors
    `firestore_client.create_firestore_client` /
    `raw_payload_store.create_local_filesystem_payload_store`:
    dependency-injected, constructed once at the API composition root,
    never a module-level singleton."""
    return FirestoreOAuthCredentialStore(client)
