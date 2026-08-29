"""Unit tests for the Phase 14.5 provider connectors (ADR-023) —
`GmailConnector`, `OutlookConnector`, and the Drive-picker fetch helper.

Every HTTP round trip is served by `httpx.MockTransport` (the injectable
`transport=` seam every connector exposes for exactly this), so there is
zero network access. `sleep` is stubbed so backoff waits are not real
time.
"""

from __future__ import annotations

import base64
from datetime import timedelta

import httpx
import pytest
from contracts.errors import (
    ConnectorFetchFailed,
    OAuthConnectionRequired,
    OAuthScopeInsufficient,
    OAuthTokenRefreshFailed,
)
from contracts.ingestion import EXTERNAL_IDENTITY_HEADER, OAuthProvider

from app.adapters.connectors.drive_picker import DrivePickerError, fetch_drive_file
from app.adapters.connectors.gmail_connector import GmailConnector
from app.adapters.connectors.outlook_connector import OutlookConnector
from app.adapters.oauth.google import DRIVE_FILE_SCOPE, GMAIL_READONLY_SCOPE
from app.adapters.oauth.microsoft import MAIL_READ_SCOPE

from ._ingestion_fakes import (
    FakeOAuthCredentialStore,
    FakeSecretResolver,
    StubOAuthClient,
    make_oauth_credential,
)

_WINDOW = timedelta(hours=24)


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _json(payload: object, status_code: int = 200) -> httpx.Response:
    return httpx.Response(status_code, json=payload)


# ---------------------------------------------------------------------------
# GmailConnector
# ---------------------------------------------------------------------------


def _gmail_message(message_id: str, *, sender: str, subject: str, body: str) -> dict[str, object]:
    return {
        "id": message_id,
        "internalDate": "1756000000000",
        "snippet": "snippet fallback",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": subject},
                {"name": "To", "value": "household@example.com"},
            ],
            "parts": [{"mimeType": "text/plain", "body": {"data": _b64url(body)}}],
        },
    }


def _gmail_connector(
    handler: httpx.MockTransport,
    *,
    credentials: FakeOAuthCredentialStore,
    sleeps: list[float] | None = None,
) -> GmailConnector:
    sink = sleeps.append if sleeps is not None else (lambda _s: None)
    return GmailConnector(
        credential_store=credentials,
        secret_resolver=FakeSecretResolver(),
        oauth_client=StubOAuthClient(),
        transport=handler,
        sleep=sink,
    )


def _gmail_creds() -> FakeOAuthCredentialStore:
    return FakeOAuthCredentialStore(
        [make_oauth_credential(granted_scopes=("openid", "email", GMAIL_READONLY_SCOPE))]
    )


def test_gmail_paginates_and_shapes_mime_into_payloads() -> None:
    pages: dict[str | None, dict[str, object]] = {
        None: {"messages": [{"id": "m1"}], "nextPageToken": "PAGE2"},
        "PAGE2": {"messages": [{"id": "m2"}]},
    }

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/messages"):
            assert request.url.params.get("q", "").startswith("after:")
            return _json(pages[request.url.params.get("pageToken")])
        if request.url.path.endswith("/messages/m1"):
            return _json(_gmail_message("m1", sender="school@example.com", subject="Trip", body="Body one"))
        if request.url.path.endswith("/messages/m2"):
            return _json(_gmail_message("m2", sender="bank@example.com", subject="Stmt", body="Body two"))
        raise AssertionError(f"unexpected request {request.url}")

    payloads = list(
        _gmail_connector(httpx.MockTransport(handle), credentials=_gmail_creds()).fetch_since(
            _WINDOW, principal="alice@example.com"
        )
    )

    assert [p.headers[EXTERNAL_IDENTITY_HEADER] for p in payloads] == ["m1", "m2"]
    assert payloads[0].text == "Body one"
    assert payloads[0].headers["from"] == "school@example.com"
    assert payloads[0].headers["subject"] == "Trip"
    assert payloads[0].media_type == "text/plain"


def test_gmail_retries_429_then_succeeds_and_records_backoff() -> None:
    attempts = {"n": 0}

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/messages")
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "1"}, json={})
        return _json({"messages": []})

    sleeps: list[float] = []
    result = list(
        _gmail_connector(httpx.MockTransport(handle), credentials=_gmail_creds(), sleeps=sleeps).fetch_since(
            _WINDOW, principal="alice@example.com"
        )
    )
    assert result == []
    assert attempts["n"] == 3
    assert len(sleeps) == 2  # two retryable 429s -> two backoff waits


def test_gmail_5xx_that_never_recovers_raises_connector_fetch_failed() -> None:
    with pytest.raises(ConnectorFetchFailed):
        _gmail_connector(
            httpx.MockTransport(lambda _r: httpx.Response(503, json={})),
            credentials=_gmail_creds(),
            sleeps=[],
        ).fetch_since(_WINDOW, principal="alice@example.com")


def test_gmail_401_is_an_auth_failure() -> None:
    with pytest.raises(OAuthTokenRefreshFailed):
        _gmail_connector(
            httpx.MockTransport(lambda _r: httpx.Response(401, json={"error": "invalid_credentials"})),
            credentials=_gmail_creds(),
        ).fetch_since(_WINDOW, principal="alice@example.com")


def test_gmail_no_connected_account_raises_connection_required() -> None:
    with pytest.raises(OAuthConnectionRequired):
        _gmail_connector(
            httpx.MockTransport(lambda _r: httpx.Response(200, json={})),
            credentials=FakeOAuthCredentialStore([]),
        ).fetch_since(_WINDOW, principal="alice@example.com")


def test_gmail_grant_missing_gmail_scope_raises_scope_insufficient() -> None:
    creds = FakeOAuthCredentialStore([make_oauth_credential(granted_scopes=("openid", "email"))])
    with pytest.raises(OAuthScopeInsufficient):
        _gmail_connector(
            httpx.MockTransport(lambda _r: httpx.Response(200, json={})), credentials=creds
        ).fetch_since(_WINDOW, principal="alice@example.com")


# ---------------------------------------------------------------------------
# OutlookConnector
# ---------------------------------------------------------------------------


def test_outlook_paginates_on_odata_nextlink_and_shapes_payloads() -> None:
    base_message: dict[str, object] = {
        "id": "g1",
        "from": {"emailAddress": {"address": "society@example.com"}},
        "subject": "Maintenance notice",
        "toRecipients": [{"emailAddress": {"address": "flat3@example.com"}}],
        "receivedDateTime": "2026-08-28T09:00:00Z",
        "body": {"contentType": "text", "content": "Lift AMC due"},
        "bodyPreview": "Lift AMC due",
    }
    page1 = {
        "value": [base_message],
        "@odata.nextLink": "https://graph.microsoft.com/v1.0/me/messages?$skip=50",
    }
    page2 = {"value": [dict(base_message, id="g2", subject="Second")]}

    def handle(request: httpx.Request) -> httpx.Response:
        if "skip=50" in str(request.url):
            return _json(page2)
        assert "receivedDateTime ge " in request.url.params.get("$filter", "")
        return _json(page1)

    creds = FakeOAuthCredentialStore(
        [
            make_oauth_credential(
                provider=OAuthProvider.MICROSOFT, granted_scopes=("openid", "email", MAIL_READ_SCOPE)
            )
        ]
    )
    connector = OutlookConnector(
        credential_store=creds,
        secret_resolver=FakeSecretResolver(),
        oauth_client=StubOAuthClient(provider=OAuthProvider.MICROSOFT),
        transport=httpx.MockTransport(handle),
        sleep=lambda _s: None,
    )
    payloads = list(connector.fetch_since(_WINDOW, principal="alice@example.com"))
    assert [p.headers[EXTERNAL_IDENTITY_HEADER] for p in payloads] == ["g1", "g2"]
    assert payloads[0].headers["from"] == "society@example.com"
    assert payloads[0].headers["subject"] == "Maintenance notice"
    assert payloads[0].text == "Lift AMC due"


def test_outlook_401_is_an_auth_failure() -> None:
    creds = FakeOAuthCredentialStore(
        [
            make_oauth_credential(
                provider=OAuthProvider.MICROSOFT, granted_scopes=("openid", "email", MAIL_READ_SCOPE)
            )
        ]
    )
    connector = OutlookConnector(
        credential_store=creds,
        secret_resolver=FakeSecretResolver(),
        oauth_client=StubOAuthClient(provider=OAuthProvider.MICROSOFT),
        transport=httpx.MockTransport(lambda _r: httpx.Response(403, json={})),
        sleep=lambda _s: None,
    )
    with pytest.raises(OAuthTokenRefreshFailed):
        connector.fetch_since(_WINDOW, principal="alice@example.com")


# ---------------------------------------------------------------------------
# Drive picker fetch helper
# ---------------------------------------------------------------------------


def test_drive_picker_rejects_unsupported_mime_before_downloading() -> None:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("alt") == "media":
            raise AssertionError("must not download bytes for an unsupported mime type")
        return _json({"id": "f1", "name": "notes.txt", "mimeType": "text/plain", "headRevisionId": "r1"})

    with pytest.raises(DrivePickerError):
        fetch_drive_file(
            file_id="f1", access_token="at", transport=httpx.MockTransport(handle), sleep=lambda _s: None
        )


def test_drive_picker_returns_payload_with_revision_scoped_identity() -> None:
    pdf_bytes = b"%PDF-1.4 minimal"

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.params.get("alt") == "media":
            return httpx.Response(200, content=pdf_bytes)
        return _json(
            {
                "id": "f9",
                "name": "warranty.pdf",
                "mimeType": "application/pdf",
                "headRevisionId": "rev42",
                "size": str(len(pdf_bytes)),
            }
        )

    payload = fetch_drive_file(
        file_id="f9", access_token="at", transport=httpx.MockTransport(handle), sleep=lambda _s: None
    )
    assert payload.binary == pdf_bytes
    assert payload.media_type == "application/pdf"
    assert payload.headers[EXTERNAL_IDENTITY_HEADER] == "f9:rev42"
    assert payload.headers["filename"] == "warranty.pdf"


def test_drive_file_scope_constant_is_the_documented_value() -> None:
    assert DRIVE_FILE_SCOPE == "https://www.googleapis.com/auth/drive.file"
