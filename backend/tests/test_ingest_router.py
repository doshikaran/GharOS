"""HTTP-level tests for `app.api.ingest_router` (ADR-023) — the one
`POST /ingest` wire and the `GET /connections` / disconnect management
routes.

The `IngestionOrchestrator` is overridden with a recording fake so these
tests prove the ROUTE's job — content-type dispatch, request shaping,
`IngestionRunResult` serialization, the 409 precondition mapping, and the
secret-free `/connections` serialization — independent of the real
pipeline, which `test_ingestion_orchestrator.py` covers end to end.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from contracts.ingestion import (
    ConnectorFailure,
    DocumentIngestOutcome,
    DocumentIngestStatus,
    IngestionRequest,
    IngestionRunResult,
    IngestionSourceKind,
    OAuthProvider,
    RawIntakePayload,
)
from fastapi.testclient import TestClient

from app.adapters.ingestion import INGESTION_SOURCE_KIND_HEADER
from app.api import ingest_router
from app.api.ingest_router import get_ingestion_orchestrator
from app.api.oauth_router import get_credential_store, get_secret_reader, get_secret_writer
from app.main import app

from ._ingestion_fakes import (
    FakeOAuthCredentialStore,
    FakeSecretResolver,
    FakeSecretWriteAdapter,
    make_oauth_credential,
)

_NOW = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)


class _RecordingOrchestrator:
    def __init__(self, result: IngestionRunResult) -> None:
        self._result = result
        self.requests: list[IngestionRequest] = []

    def run(self, request: IngestionRequest) -> IngestionRunResult:
        self.requests.append(request)
        return self._result


def _run_result(
    *,
    outcomes: tuple[DocumentIngestOutcome, ...] = (),
    connector_failures: tuple[ConnectorFailure, ...] = (),
    sources_scanned: tuple[IngestionSourceKind, ...] = (),
) -> IngestionRunResult:
    return IngestionRunResult(
        run_id="run-123",
        idempotency_scope="manual-scan:x",
        started_at=_NOW,
        finished_at=_NOW,
        sources_scanned=sources_scanned,
        outcomes=outcomes,
        new_node_ids=tuple(nid for o in outcomes for nid in o.new_node_ids),
        connector_failures=connector_failures,
    )


def _ingested_outcome() -> DocumentIngestOutcome:
    return DocumentIngestOutcome(
        content_hash="hash-1",
        source=IngestionSourceKind.GMAIL,
        status=DocumentIngestStatus.INGESTED,
        source_document_id="doc:1",
        external_ref="m1",
        classified_type_id="receipt",
        new_node_ids=("doc:1", "vendor:acme"),
        new_edge_ids=("edge:1",),
        detail="",
    )


@pytest.fixture
def ingest_client() -> Iterator[TestClient]:
    creds = FakeOAuthCredentialStore(
        [
            make_oauth_credential(
                granted_scopes=("openid", "email"), secret_ref="projects/p/secrets/s/versions/1"
            )
        ]
    )
    writer = FakeSecretWriteAdapter()
    reader = FakeSecretResolver()
    app.dependency_overrides[get_credential_store] = lambda: creds
    app.dependency_overrides[get_secret_writer] = lambda: writer
    app.dependency_overrides[get_secret_reader] = lambda: reader
    client = TestClient(app)
    client.creds = creds
    client.secret_writer = writer
    try:
        yield client
    finally:
        app.dependency_overrides.clear()


def _use_orchestrator(orch: _RecordingOrchestrator) -> None:
    app.dependency_overrides[get_ingestion_orchestrator] = lambda: orch


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------


def test_ingest_json_scan_returns_serialized_run_result(ingest_client: TestClient) -> None:
    orch = _RecordingOrchestrator(_run_result(outcomes=(_ingested_outcome(),)))
    _use_orchestrator(orch)

    response = ingest_client.post(
        "/ingest",
        json={
            "sources": ["gmail"],
            "window_seconds": 86400,
            "principal": "alice@example.com",
            "idempotency_scope": "manual-scan:2026-08-30",
            "triggered_by": "person:alice",
            "household_id": "gharos-demo-household",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["run_id"] == "run-123"
    assert body["new_node_ids"] == ["doc:1", "vendor:acme"]
    assert body["outcomes"][0]["status"] == "ingested"
    assert body["outcomes"][0]["new_edge_ids"] == ["edge:1"]
    assert set(body.keys()) == {
        "run_id",
        "idempotency_scope",
        "started_at",
        "finished_at",
        "sources_scanned",
        "outcomes",
        "new_node_ids",
        "connector_failures",
        "run_errors",
    }

    sent = orch.requests[0]
    assert sent.sources == (IngestionSourceKind.GMAIL,)
    assert sent.principal == "alice@example.com"
    assert sent.window is not None and sent.window.total_seconds() == 86400
    assert sent.triggered_by == "person:alice"


def test_ingest_json_scan_missing_idempotency_scope_is_422(ingest_client: TestClient) -> None:
    _use_orchestrator(_RecordingOrchestrator(_run_result()))
    response = ingest_client.post(
        "/ingest", json={"sources": ["gmail"], "window_seconds": 3600, "principal": "a@b.com"}
    )
    assert response.status_code == 422


def test_ingest_multipart_upload_becomes_inline_payloads(ingest_client: TestClient) -> None:
    orch = _RecordingOrchestrator(_run_result(outcomes=(_ingested_outcome(),)))
    _use_orchestrator(orch)

    response = ingest_client.post(
        "/ingest",
        data={"idempotency_scope": "upload:1", "triggered_by": "person:bob"},
        files={"files": ("receipt.png", b"\x89PNG fake bytes", "image/png")},
    )
    assert response.status_code == 200
    sent = orch.requests[0]
    assert sent.sources == ()
    assert len(sent.inline_payloads) == 1
    payload = sent.inline_payloads[0]
    assert payload.media_type == "image/png"
    assert payload.binary == b"\x89PNG fake bytes"
    assert payload.headers[INGESTION_SOURCE_KIND_HEADER] == IngestionSourceKind.DIRECT_UPLOAD.value
    assert payload.headers["filename"] == "receipt.png"


def test_ingest_multipart_rejects_unsupported_media_type(ingest_client: TestClient) -> None:
    _use_orchestrator(_RecordingOrchestrator(_run_result()))
    response = ingest_client.post(
        "/ingest",
        data={"idempotency_scope": "upload:2"},
        files={"files": ("notes.txt", b"just text", "text/plain")},
    )
    assert response.status_code == 415


def test_ingest_drive_file_ids_fetch_and_join_the_wire(
    ingest_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.adapters.oauth.google import DRIVE_FILE_SCOPE

    ingest_client.creds.put(
        make_oauth_credential(
            provider=OAuthProvider.GOOGLE, granted_scopes=("openid", "email", DRIVE_FILE_SCOPE)
        )
    )
    orch = _RecordingOrchestrator(_run_result(outcomes=(_ingested_outcome(),)))
    _use_orchestrator(orch)
    monkeypatch.setattr(ingest_router, "_drive_access_token", lambda *a, **k: "drive-access-token")

    def fake_fetch(*, file_id: str, access_token: str, principal: str = "") -> RawIntakePayload:
        assert access_token == "drive-access-token"
        return RawIntakePayload(
            text=None,
            binary=b"%PDF-1.7",
            media_type="application/pdf",
            headers={
                "external_identity": f"{file_id}:rev1",
                INGESTION_SOURCE_KIND_HEADER: IngestionSourceKind.DRIVE_PICKER.value,
            },
        )

    monkeypatch.setattr(ingest_router, "fetch_drive_file", fake_fetch)

    response = ingest_client.post(
        "/ingest", json={"drive_file_ids": ["fileA", "fileB"], "idempotency_scope": "drive:1"}
    )
    assert response.status_code == 200
    sent = orch.requests[0]
    assert [p.headers["external_identity"] for p in sent.inline_payloads] == ["fileA:rev1", "fileB:rev1"]


def test_ingest_single_source_auth_failure_maps_to_409_reconnect(ingest_client: TestClient) -> None:
    orch = _RecordingOrchestrator(
        _run_result(
            connector_failures=(
                ConnectorFailure(
                    source=IngestionSourceKind.GMAIL,
                    principal="alice@example.com",
                    reason="google token refresh failed: invalid_grant",
                    is_auth_failure=True,
                ),
            )
        )
    )
    _use_orchestrator(orch)
    response = ingest_client.post(
        "/ingest",
        json={
            "sources": ["gmail"],
            "window_seconds": 3600,
            "principal": "alice@example.com",
            "idempotency_scope": "manual:1",
        },
    )
    assert response.status_code == 409
    body = response.json()
    assert body["provider"] == "google"
    assert body["principal"] == "alice@example.com"
    assert "invalid_grant" in body["detail"]


# ---------------------------------------------------------------------------
# GET /connections + disconnect
# ---------------------------------------------------------------------------


def test_list_connections_omits_secret_ref(ingest_client: TestClient) -> None:
    response = ingest_client.get("/connections")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 1
    row = rows[0]
    assert "secret_ref" not in row
    assert set(row.keys()) == {
        "provider",
        "principal",
        "granted_scopes",
        "connected_at",
        "last_scan_at",
        "revoked_at",
    }
    assert row["revoked_at"] is None


def test_disconnect_revokes_record_and_destroys_secret(ingest_client: TestClient) -> None:
    response = ingest_client.post("/connections/google/alice@example.com/disconnect")
    assert response.status_code == 200
    assert response.json()["status"] == "disconnected"
    assert ingest_client.creds.revoked[0][:2] == (
        OAuthProvider.GOOGLE,
        "alice@example.com",
    )
    assert ingest_client.secret_writer.destroyed == ["s"]


def test_disconnect_unknown_connection_is_404(ingest_client: TestClient) -> None:
    assert ingest_client.post("/connections/google/nobody@example.com/disconnect").status_code == 404
