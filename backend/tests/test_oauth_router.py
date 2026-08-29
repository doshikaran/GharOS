"""HTTP-level tests for `app.api.oauth_router` (ADR-022) — the OAuth
consent-start / callback / picker-token routes.

`get_oauth_client_for` is monkeypatched to a `StubOAuthClient` (no
provider round trips); the pending store is the in-memory fake; the
credential store is the REAL `FirestoreOAuthCredentialStore` against the
emulator, so "the persisted document carries no token material" is proven
against a real Firestore document, not a mock (Gate 14.5).
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from google.cloud import firestore

from app.api import oauth_router
from app.api.oauth_router import (
    get_credential_store,
    get_pending_store,
    get_secret_reader,
    get_secret_writer,
)
from app.main import app
from app.persistence.codecs.oauth import _FIELDS as OAUTH_CREDENTIAL_DOC_FIELDS
from app.persistence.oauth_credential_store import create_oauth_credential_store

from ._ingestion_fakes import (
    FakeSecretResolver,
    FakeSecretWriteAdapter,
    InMemoryOAuthPendingStore,
    StubOAuthClient,
)

_TOKEN_SHAPED_KEYS = {"refresh_token", "access_token", "code", "client_secret", "token", "id_token"}


@pytest.fixture
def oauth_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    pending = InMemoryOAuthPendingStore()
    writer = FakeSecretWriteAdapter()
    reader = FakeSecretResolver()
    app.dependency_overrides[get_pending_store] = lambda: pending
    app.dependency_overrides[get_secret_writer] = lambda: writer
    app.dependency_overrides[get_secret_reader] = lambda: reader
    monkeypatch.setattr(
        oauth_router,
        "get_oauth_client_for",
        lambda provider_slug, settings, reader: StubOAuthClient(principal="alice@example.com"),
    )
    client = TestClient(app, follow_redirects=False)
    client.pending = pending
    client.secret_writer = writer
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def test_start_redirects_to_provider_and_records_pending(oauth_client: TestClient) -> None:
    response = oauth_client.get("/oauth/google/start", params={"principal_hint": "alice@example.com"})
    assert response.status_code == 302
    assert response.headers["location"].startswith("https://provider.example/auth?state=")
    # exactly one pending handshake recorded
    assert len(oauth_client.pending._by_state) == 1


def test_start_unknown_provider_is_404(oauth_client: TestClient) -> None:
    assert oauth_client.get("/oauth/frobnicate/start").status_code == 404


def test_callback_provider_error_redirects_with_denied_marker(oauth_client: TestClient) -> None:
    response = oauth_client.get("/oauth/google/callback", params={"error": "access_denied"})
    assert response.status_code == 302
    assert "connect=denied" in response.headers["location"]
    assert "reason=access_denied" in response.headers["location"]


def test_callback_missing_state_or_code_is_400(oauth_client: TestClient) -> None:
    assert oauth_client.get("/oauth/google/callback", params={"code": "x"}).status_code == 400
    assert oauth_client.get("/oauth/google/callback", params={"state": "x"}).status_code == 400


def test_callback_unknown_state_is_400(oauth_client: TestClient) -> None:
    response = oauth_client.get("/oauth/google/callback", params={"state": "never-issued", "code": "c"})
    assert response.status_code == 400


def test_full_consent_flow_persists_a_tokenless_credential_document(
    oauth_client: TestClient, firestore_client: firestore.Client
) -> None:
    store = create_oauth_credential_store(firestore_client)
    app.dependency_overrides[get_credential_store] = lambda: store

    start = oauth_client.get("/oauth/google/start")
    state = start.headers["location"].split("state=", 1)[1].split("&", 1)[0]

    callback = oauth_client.get("/oauth/google/callback", params={"state": state, "code": "auth-code"})
    assert callback.status_code == 302
    assert "connect=ok" in callback.headers["location"]

    # the refresh token went to Secret Manager, not Firestore
    assert oauth_client.secret_writer.put_calls == [
        (
            "gharos-oauth-refresh--google--alice-example-com",
            "refresh-token-from-exchange",
        )
    ]

    raw = firestore_client.collection("oauth_credentials").document("google:alice@example.com").get()
    assert raw.exists
    doc = raw.to_dict()
    assert doc is not None
    assert set(doc.keys()) == set(OAUTH_CREDENTIAL_DOC_FIELDS)
    assert _TOKEN_SHAPED_KEYS.isdisjoint(doc.keys())
    assert "refresh-token" not in " ".join(str(v) for v in doc.values())


def test_state_is_single_use(oauth_client: TestClient, firestore_client: firestore.Client) -> None:
    store = create_oauth_credential_store(firestore_client)
    app.dependency_overrides[get_credential_store] = lambda: store
    state = oauth_client.get("/oauth/google/start").headers["location"].split("state=", 1)[1].split("&", 1)[0]

    first = oauth_client.get("/oauth/google/callback", params={"state": state, "code": "c1"})
    second = oauth_client.get("/oauth/google/callback", params={"state": state, "code": "c2"})
    assert first.status_code == 302
    assert second.status_code == 400  # the nonce was consumed
