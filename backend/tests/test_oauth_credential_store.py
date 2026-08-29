"""`FirestoreOAuthCredentialStore` (Phase 14.5, ADR-023 §6) against the
real Firestore emulator.

Proves: `OAuthCredential` round-trips field-for-field; `mark_revoked` is a
write-once soft delete that `get` still surfaces but `list_active`
excludes; `touch_last_scan` moves only `last_scan_at`; and — the Gate
14.5 security item — a stored credential document carries no token-shaped
material, only the seven `OAuthCredential` fields (`secret_ref` being a
Secret Manager resource-name string, never a token).
"""

from __future__ import annotations

import dataclasses
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from contracts.ingestion import OAuthCredential, OAuthProvider
from google.cloud import firestore

from app.persistence.codecs.common import NaiveDatetimeError
from app.persistence.codecs.oauth import _FIELDS
from app.persistence.conformance import _oauth_credential_store_conforms
from app.persistence.errors import OAuthCredentialNotFound
from app.persistence.oauth_credential_store import (
    FirestoreOAuthCredentialStore,
    create_oauth_credential_store,
)

_OAUTH_CREDENTIALS_COLLECTION = "oauth_credentials"

CONNECTED_AT = datetime(2026, 8, 29, 9, 0, tzinfo=UTC)
SCAN_AT = datetime(2026, 8, 29, 14, 30, tzinfo=UTC)
REVOKED_AT = datetime(2026, 8, 30, 8, 0, tzinfo=UTC)

_SECRET_REF = "projects/gharos-local/secrets/gharos-oauth-refresh--google--alice-example-com/versions/latest"

# A JWT is header.payload.signature, each a base64url segment; the header
# segment always begins `eyJ` (base64 of `{"`). Real OAuth access tokens
# for Google are JWTs; refresh tokens are long opaque `1//...` strings.
_JWT_RE = re.compile(r"^eyJ[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}\.[A-Za-z0-9_-]{4,}$")
_SECRET_RESOURCE_RE = re.compile(r"^projects/[^/]+/secrets/[^/]+/versions/[^/]+$")


@pytest.fixture
def credential_store(
    firestore_client: firestore.Client,
) -> FirestoreOAuthCredentialStore:
    return create_oauth_credential_store(firestore_client)


def _make_credential(
    *,
    provider: OAuthProvider = OAuthProvider.GOOGLE,
    principal: str = "alice@example.com",
    granted_scopes: tuple[str, ...] = (
        "https://www.googleapis.com/auth/gmail.readonly",
        "https://www.googleapis.com/auth/drive.file",
    ),
    last_scan_at: datetime | None = None,
    revoked_at: datetime | None = None,
) -> OAuthCredential:
    return OAuthCredential(
        provider=provider,
        principal=principal,
        granted_scopes=granted_scopes,
        secret_ref=_SECRET_REF,
        connected_at=CONNECTED_AT,
        last_scan_at=last_scan_at,
        revoked_at=revoked_at,
    )


def _raw_document(client: firestore.Client, credential: OAuthCredential) -> dict[str, Any]:
    snap = client.collection(_OAUTH_CREDENTIALS_COLLECTION).document(credential.storage_key).get()
    assert snap.exists
    data = snap.to_dict()
    assert data is not None
    return data


def _all_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _all_strings(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _all_strings(item)


class TestConformance:
    def test_conformance_factory_constructs(self, firestore_client: firestore.Client) -> None:
        assert _oauth_credential_store_conforms(firestore_client) is not None


class TestRoundTrip:
    def test_put_then_get_is_field_equal(self, credential_store: FirestoreOAuthCredentialStore) -> None:
        credential = _make_credential(last_scan_at=SCAN_AT)
        credential_store.put(credential)

        got = credential_store.get(OAuthProvider.GOOGLE, "alice@example.com")
        assert got is not None
        assert got.provider is OAuthProvider.GOOGLE
        assert got.principal == credential.principal
        assert got.granted_scopes == credential.granted_scopes
        assert got.secret_ref == credential.secret_ref
        assert got.connected_at == credential.connected_at
        assert got.last_scan_at == credential.last_scan_at
        assert got.revoked_at is None
        assert got.is_active is True
        assert got.storage_key == "google:alice@example.com"

    def test_get_miss_returns_none(self, credential_store: FirestoreOAuthCredentialStore) -> None:
        assert credential_store.get(OAuthProvider.MICROSOFT, "nobody@example.com") is None

    def test_put_replaces_prior_row_for_same_account(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        credential_store.put(_make_credential(granted_scopes=("scope.a",)))
        credential_store.put(_make_credential(granted_scopes=("scope.a", "scope.b")))

        got = credential_store.get(OAuthProvider.GOOGLE, "alice@example.com")
        assert got is not None
        assert got.granted_scopes == ("scope.a", "scope.b")

    def test_naive_connected_at_is_rejected(self, credential_store: FirestoreOAuthCredentialStore) -> None:
        naive = OAuthCredential(
            provider=OAuthProvider.GOOGLE,
            principal="alice@example.com",
            granted_scopes=("scope.a",),
            secret_ref=_SECRET_REF,
            connected_at=datetime(2026, 8, 29, 9, 0),
        )
        with pytest.raises(NaiveDatetimeError):
            credential_store.put(naive)


class TestListActive:
    def test_list_active_excludes_revoked(self, credential_store: FirestoreOAuthCredentialStore) -> None:
        credential_store.put(_make_credential(principal="alice@example.com"))
        credential_store.put(_make_credential(principal="bob@example.com"))
        credential_store.put(
            _make_credential(provider=OAuthProvider.MICROSOFT, principal="carol@example.com")
        )
        credential_store.mark_revoked(OAuthProvider.MICROSOFT, "carol@example.com", revoked_at=REVOKED_AT)

        active = credential_store.list_active()
        principals = sorted(c.principal for c in active)
        assert principals == ["alice@example.com", "bob@example.com"]
        assert all(c.is_active for c in active)

    def test_list_active_empty_when_nothing_stored(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        assert credential_store.list_active() == ()


class TestMarkRevoked:
    def test_revoked_row_is_still_gettable_but_inactive(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        credential_store.put(_make_credential())
        credential_store.mark_revoked(OAuthProvider.GOOGLE, "alice@example.com", revoked_at=REVOKED_AT)

        got = credential_store.get(OAuthProvider.GOOGLE, "alice@example.com")
        assert got is not None
        assert got.revoked_at == REVOKED_AT
        assert got.is_active is False

    def test_revoked_at_is_write_once(self, credential_store: FirestoreOAuthCredentialStore) -> None:
        credential_store.put(_make_credential())
        credential_store.mark_revoked(OAuthProvider.GOOGLE, "alice@example.com", revoked_at=REVOKED_AT)
        later = REVOKED_AT + timedelta(days=2)
        credential_store.mark_revoked(OAuthProvider.GOOGLE, "alice@example.com", revoked_at=later)

        got = credential_store.get(OAuthProvider.GOOGLE, "alice@example.com")
        assert got is not None
        assert got.revoked_at == REVOKED_AT  # first timestamp wins, never overwritten

    def test_mark_revoked_on_missing_row_raises(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        with pytest.raises(OAuthCredentialNotFound):
            credential_store.mark_revoked(OAuthProvider.GOOGLE, "ghost@example.com", revoked_at=REVOKED_AT)

    def test_mark_revoked_naive_timestamp_rejected(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        credential_store.put(_make_credential())
        with pytest.raises(NaiveDatetimeError):
            credential_store.mark_revoked(
                OAuthProvider.GOOGLE,
                "alice@example.com",
                revoked_at=datetime(2026, 8, 30, 8, 0),
            )


class TestTouchLastScan:
    def test_touch_last_scan_updates_only_that_field(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        credential = _make_credential(last_scan_at=None)
        credential_store.put(credential)

        credential_store.touch_last_scan(OAuthProvider.GOOGLE, "alice@example.com", at=SCAN_AT)

        got = credential_store.get(OAuthProvider.GOOGLE, "alice@example.com")
        assert got is not None
        assert got.last_scan_at == SCAN_AT
        expected = dataclasses.replace(credential, last_scan_at=SCAN_AT)
        assert got == expected  # every other field byte-for-byte unchanged

    def test_touch_last_scan_advances_existing_value(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        credential_store.put(_make_credential(last_scan_at=SCAN_AT))
        newer = SCAN_AT + timedelta(hours=6)
        credential_store.touch_last_scan(OAuthProvider.GOOGLE, "alice@example.com", at=newer)

        got = credential_store.get(OAuthProvider.GOOGLE, "alice@example.com")
        assert got is not None
        assert got.last_scan_at == newer

    def test_touch_last_scan_on_missing_row_raises(
        self, credential_store: FirestoreOAuthCredentialStore
    ) -> None:
        with pytest.raises(OAuthCredentialNotFound):
            credential_store.touch_last_scan(OAuthProvider.GOOGLE, "ghost@example.com", at=SCAN_AT)


class TestNoTokenMaterialPersisted:
    """Gate 14.5: OAuth tokens live in Secret Manager, never in Firestore.
    The `OAuthCredentialStore` API has no parameter for a token, and the
    stored document proves it — its key set is exactly the seven
    `OAuthCredential` fields, no value is JWT-shaped, and `secret_ref` is
    a Secret Manager resource name, not a secret."""

    def test_stored_document_has_exactly_the_seven_credential_fields(
        self, credential_store: FirestoreOAuthCredentialStore, firestore_client: firestore.Client
    ) -> None:
        credential = _make_credential(last_scan_at=SCAN_AT)
        credential_store.put(credential)
        data = _raw_document(firestore_client, credential)
        assert set(data.keys()) == set(_FIELDS)

    def test_no_stored_value_is_jwt_shaped(
        self, credential_store: FirestoreOAuthCredentialStore, firestore_client: firestore.Client
    ) -> None:
        credential = _make_credential(last_scan_at=SCAN_AT, revoked_at=REVOKED_AT)
        credential_store.put(credential)
        credential_store.mark_revoked(OAuthProvider.GOOGLE, "alice@example.com", revoked_at=REVOKED_AT)
        data = _raw_document(firestore_client, credential)
        for text in _all_strings(data):
            assert not _JWT_RE.match(text), f"JWT-shaped value in stored credential: {text!r}"

    def test_secret_ref_is_a_resource_name_not_a_secret(
        self, credential_store: FirestoreOAuthCredentialStore, firestore_client: firestore.Client
    ) -> None:
        credential = _make_credential()
        credential_store.put(credential)
        data = _raw_document(firestore_client, credential)
        assert _SECRET_RESOURCE_RE.match(data["secret_ref"])
