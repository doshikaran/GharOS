"""GharOS — the one ingestion entry point and the connection-management
surface (Phase 14.5, ADR-023 / ADR-022). E3's own router, registered in
`app.main` next to `app.api.oauth_router` / `app.api.voice_router`.

Routes:

- `POST /ingest` — the single wire (ADR-023 §1). Accepts:
    * `application/json` window-scan:
      `{sources, window_seconds, principal, idempotency_scope,
        triggered_by, household_id}` -> a connector scan.
    * `application/json` Drive-picker selection:
      `{drive_file_ids: [...], idempotency_scope, triggered_by,
        household_id}` -> each picked file's bytes are fetched server-side
      with the stored `drive.file` grant and joined as `inline_payloads`.
    * `multipart/form-data` upload: `files` parts + `idempotency_scope` /
      `triggered_by` / `household_id` form fields -> `inline_payloads`.
  Runs `IngestionOrchestrator.run` on a worker thread
  (`run_in_threadpool`) and returns the `IngestionRunResult` as JSON. A
  single-source scan against an account with no valid grant returns
  `409` with `{provider, principal, detail}` — never a fabricated empty
  success (Gate 14.5, invariant #7).

- `GET /connections` — every active `OAuthCredential`, serialized WITHOUT
  `secret_ref` or any token material (spec §23).

- `POST /connections/{provider}/{principal}/disconnect` — mark the record
  revoked (soft delete), destroy the Secret Manager refresh-token
  version(s), and best-effort revoke the grant at the provider
  (ADR-022 §5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import httpx
import structlog
from contracts.graph_types import Person
from contracts.ingestion import (
    DocumentIngestOutcome,
    IngestionRequest,
    IngestionRunResult,
    IngestionSourceKind,
    OAuthCredential,
    OAuthProvider,
    RawIntakePayload,
)
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse
from google.cloud import firestore

from app.adapters.connectors.drive_picker import DrivePickerError, fetch_drive_file
from app.adapters.connectors.gmail_connector import GmailConnector
from app.adapters.connectors.outlook_connector import OutlookConnector
from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.document_upload_adapter import SUPPORTED_MEDIA_TYPES
from app.adapters.ingestion import INGESTION_SOURCE_KIND_HEADER
from app.adapters.oauth.errors import OAuthExchangeFailed
from app.adapters.oauth.google import DRIVE_FILE_SCOPE, REVOKE_ENDPOINT
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.adapters.secret_manager import SecretManagerAdapter, SecretManagerError, SecretManagerWriteAdapter
from app.agents.intake.document_extraction import DocumentExtractionAgent
from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies import register_all_strategies
from app.api.oauth_router import (
    get_credential_store,
    get_oauth_client_for,
    get_secret_reader,
    get_secret_writer,
    provider_or_404,
    secret_id_from_ref,
)
from app.audit.audit_log import FirestoreAuditLog
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_client import create_firestore_client
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.ingestion_dedupe_store import create_ingestion_dedupe_store
from app.persistence.oauth_credential_store import FirestoreOAuthCredentialStore
from app.persistence.raw_payload_store import RawPayloadStore, create_local_filesystem_payload_store
from app.pipelines.ingestion_orchestrator import IngestionOrchestrator
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import ModelRouter
from app.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["ingest"])

DEMO_HOUSEHOLD_ID = "gharos-demo-household"
"""Single-household framing (spec §3.1). Matches
`frontend/lib/connections.ts`'s `DEMO_HOUSEHOLD_ID` — the value the
Connections page sends and the value the voice path uses. The default
when a `POST /ingest` body / form omits `household_id`."""

_MAX_UPLOAD_FILES = 10
_MAX_UPLOAD_BYTES = 25 * 1024 * 1024


# ---------------------------------------------------------------------------
# Composition root — the IngestionOrchestrator and its dependencies.
# Mirrors app.api.voice_router's per-request `get_*` provider chain; no
# module-level singletons.
# ---------------------------------------------------------------------------


def get_firestore_client(settings: Annotated[Settings, Depends(get_settings)]) -> firestore.Client:
    return create_firestore_client(settings)


def get_graph_store(
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> FirestoreGraphStore:
    return FirestoreGraphStore(client)


def get_payload_store(settings: Annotated[Settings, Depends(get_settings)]) -> RawPayloadStore:
    return create_local_filesystem_payload_store(settings)


def _gemini_client(settings: Settings) -> GeminiClient:
    return GeminiClient(
        router=ModelRouter(
            project_id=settings.gcp_project_id,
            location=settings.vertex_ai_location,
            location_pro=settings.vertex_ai_location_pro,
            model_flash=settings.gemini_model_flash,
            model_pro=settings.gemini_model_pro,
        )
    )


def _build_document_registry() -> DocumentTypeRegistry:
    registry = DocumentTypeRegistry()
    register_all_strategies(registry)
    return registry


def _build_connectors(
    settings: Settings,
    reader: SecretManagerAdapter,
    credential_store: FirestoreOAuthCredentialStore,
) -> dict[IngestionSourceKind, GmailConnector | OutlookConnector]:
    """One connector per provider that is actually configured. An
    unconfigured provider is simply absent — a scan request naming it
    then produces an honest `ConnectorFailure` ('no connector
    registered'), never a silent empty result."""
    connectors: dict[IngestionSourceKind, GmailConnector | OutlookConnector] = {}
    if settings.google_oauth_client_id and settings.google_oauth_client_secret_ref:
        try:
            connectors[IngestionSourceKind.GMAIL] = GmailConnector(
                credential_store=credential_store,
                secret_resolver=reader,
                oauth_client=get_oauth_client_for("google", settings, reader),
            )
        except HTTPException as exc:  # client-secret unreadable etc. — skip, don't 503 an upload
            logger.warning("ingest.connectors.google_unavailable", detail=str(exc.detail))
    if settings.microsoft_oauth_client_id and settings.microsoft_oauth_client_secret_ref:
        try:
            connectors[IngestionSourceKind.OUTLOOK] = OutlookConnector(
                credential_store=credential_store,
                secret_resolver=reader,
                oauth_client=get_oauth_client_for("microsoft", settings, reader),
            )
        except HTTPException as exc:
            logger.warning("ingest.connectors.microsoft_unavailable", detail=str(exc.detail))
    return connectors


def build_ingestion_orchestrator(
    *,
    settings: Settings,
    firestore_client: firestore.Client,
    graph_store: FirestoreGraphStore,
    payload_store: RawPayloadStore,
    reader: SecretManagerAdapter,
    credential_store: FirestoreOAuthCredentialStore,
) -> IngestionOrchestrator:
    """Constructs one real `IngestionOrchestrator` with every Phase 3
    stage wired to its real implementation (A2/A3/A5 on Gemini via the
    real `ModelRouter`), the real provenance-guarded `FirestoreGraph
    Writer`, the real `FirestoreAuditLog`, and the real Firestore dedupe
    store. `firestore_client` backs the dedupe store, the audit log, and
    (via `graph_store`) the graph writer — one client, one emulator/
    project."""
    gemini = _gemini_client(settings)
    registry = _build_document_registry()

    def known_people() -> tuple[Person, ...]:
        return tuple(graph_store.all_current_nodes((Person,)))

    return IngestionOrchestrator(
        connectors=_build_connectors(settings, reader, credential_store),
        dedupe_store=create_ingestion_dedupe_store(firestore_client),
        raw_payload_store=payload_store,
        intake_router=IntakeRouter(
            gemini_client=gemini, registry=registry, gap_log=RegistryGapLog(InMemoryRegistryGapStore())
        ),
        extraction_agent=DocumentExtractionAgent(gemini_client=gemini),
        entity_resolution_agent=EntityResolutionAgent(gemini_client=gemini),
        registry=registry,
        graph_writer=FirestoreGraphWriter(graph_store),
        audit_log=FirestoreAuditLog(firestore_client),
        credential_store=credential_store,
        known_people_provider=known_people,
    )


def get_ingestion_orchestrator(
    settings: Annotated[Settings, Depends(get_settings)],
    firestore_client: Annotated[firestore.Client, Depends(get_firestore_client)],
    graph_store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
    payload_store: Annotated[RawPayloadStore, Depends(get_payload_store)],
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
) -> IngestionOrchestrator:
    return build_ingestion_orchestrator(
        settings=settings,
        firestore_client=firestore_client,
        graph_store=graph_store,
        payload_store=payload_store,
        reader=reader,
        credential_store=credential_store,
    )


# ---------------------------------------------------------------------------
# POST /ingest
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _UploadFile:
    data: bytes
    media_type: str
    filename: str


@dataclass(frozen=True, slots=True)
class _IngestPlan:
    """Everything needed to run one ingest, resolved from the request
    before the blocking work is offloaded to a worker thread."""

    mode: Literal["scan", "upload", "drive"]
    idempotency_scope: str
    triggered_by: str
    household_id: str
    sources: tuple[IngestionSourceKind, ...] = ()
    window: timedelta | None = None
    principal: str | None = None
    uploads: tuple[_UploadFile, ...] = ()
    drive_file_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _PreconditionFailure:
    provider: str | None
    principal: str | None
    detail: str
    http_status: int


def _meta_from(mapping: dict[str, Any]) -> tuple[str, str, str]:
    idempotency_scope = str(mapping.get("idempotency_scope") or "").strip()
    if not idempotency_scope:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`idempotency_scope` is required")
    triggered_by = str(mapping.get("triggered_by") or "manual").strip() or "manual"
    household_id = str(mapping.get("household_id") or DEMO_HOUSEHOLD_ID).strip() or DEMO_HOUSEHOLD_ID
    return idempotency_scope, triggered_by, household_id


def _plan_from_json(body: dict[str, Any]) -> _IngestPlan:
    idempotency_scope, triggered_by, household_id = _meta_from(body)

    raw_ids = body.get("drive_file_ids")
    single_id = body.get("drive_file_id")
    drive_ids: list[str] = []
    if isinstance(raw_ids, list):
        drive_ids = [str(x) for x in raw_ids if str(x).strip()]
    elif isinstance(single_id, str) and single_id.strip():
        drive_ids = [single_id.strip()]
    if drive_ids:
        return _IngestPlan(
            mode="drive",
            idempotency_scope=idempotency_scope,
            triggered_by=triggered_by,
            household_id=household_id,
            drive_file_ids=tuple(drive_ids),
        )

    raw_sources = body.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "a JSON /ingest body needs either `sources` (a scan) or `drive_file_ids` (a Drive selection)",
        )
    try:
        sources = tuple(IngestionSourceKind(str(s)) for s in raw_sources)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"unknown source kind: {exc}") from exc

    window_raw = body.get("window_seconds")
    if not isinstance(window_raw, (int, float)) or isinstance(window_raw, bool) or window_raw <= 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "`window_seconds` must be a positive number"
        )
    principal = str(body.get("principal") or "").strip()
    if not principal:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "`principal` is required for a scan")

    return _IngestPlan(
        mode="scan",
        idempotency_scope=idempotency_scope,
        triggered_by=triggered_by,
        household_id=household_id,
        sources=sources,
        window=timedelta(seconds=float(window_raw)),
        principal=principal,
    )


async def _plan_from_multipart(request: Request) -> _IngestPlan:
    form = await request.form()
    idempotency_scope, triggered_by, household_id = _meta_from(
        {k: form.get(k) for k in ("idempotency_scope", "triggered_by", "household_id")}
    )
    uploads: list[_UploadFile] = []
    for item in form.getlist("files"):
        if isinstance(item, str):
            continue
        data = await item.read()
        if not data:
            continue
        if len(data) > _MAX_UPLOAD_BYTES:
            raise HTTPException(
                status.HTTP_413_CONTENT_TOO_LARGE,
                f"'{item.filename}' is {len(data)} bytes, over the {_MAX_UPLOAD_BYTES}-byte limit",
            )
        media_type = item.content_type or "application/octet-stream"
        if media_type not in SUPPORTED_MEDIA_TYPES:
            raise HTTPException(
                status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                f"'{item.filename}' has media type {media_type!r}; expected one of "
                f"{sorted(SUPPORTED_MEDIA_TYPES)}",
            )
        uploads.append(_UploadFile(data=data, media_type=media_type, filename=item.filename or "upload"))
        if len(uploads) > _MAX_UPLOAD_FILES:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, f"at most {_MAX_UPLOAD_FILES} files per request"
            )
    if not uploads:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no usable `files` parts in the upload")
    return _IngestPlan(
        mode="upload",
        idempotency_scope=idempotency_scope,
        triggered_by=triggered_by,
        household_id=household_id,
        uploads=tuple(uploads),
    )


def _upload_payload(upload: _UploadFile) -> RawIntakePayload:
    return RawIntakePayload(
        text=None,
        binary=upload.data,
        media_type=upload.media_type,
        headers={
            INGESTION_SOURCE_KIND_HEADER: IngestionSourceKind.DIRECT_UPLOAD.value,
            "filename": upload.filename,
        },
        received_at=datetime.now(UTC),
    )


def _google_principal(credential_store: FirestoreOAuthCredentialStore) -> str | None:
    for credential in credential_store.list_active():
        if credential.provider is OAuthProvider.GOOGLE and DRIVE_FILE_SCOPE in credential.granted_scopes:
            return credential.principal
    return None


def _execute_plan(
    plan: _IngestPlan,
    *,
    orchestrator: IngestionOrchestrator,
    settings: Settings,
    reader: SecretManagerAdapter,
    credential_store: FirestoreOAuthCredentialStore,
) -> IngestionRunResult | _PreconditionFailure:
    """The blocking body of `POST /ingest`, run on a worker thread. Any
    Drive fetch happens here too (it is a network call)."""
    if plan.mode == "scan":
        assert plan.window is not None and plan.principal is not None
        request = IngestionRequest(
            idempotency_scope=plan.idempotency_scope,
            triggered_by=plan.triggered_by,
            household_id=plan.household_id,
            sources=plan.sources,
            window=plan.window,
            principal=plan.principal,
        )
        result = orchestrator.run(request)
        precondition = _single_source_precondition(plan, result)
        return precondition or result

    if plan.mode == "upload":
        request = IngestionRequest(
            idempotency_scope=plan.idempotency_scope,
            triggered_by=plan.triggered_by,
            household_id=plan.household_id,
            inline_payloads=tuple(_upload_payload(u) for u in plan.uploads),
        )
        return orchestrator.run(request)

    # plan.mode == "drive"
    principal = _google_principal(credential_store)
    if principal is None:
        return _PreconditionFailure(
            provider="google",
            principal=None,
            detail="no connected Google account with the Drive picker scope — connect Google first",
            http_status=status.HTTP_409_CONFLICT,
        )
    access_token = _drive_access_token(settings, reader, credential_store, principal)
    if isinstance(access_token, _PreconditionFailure):
        return access_token

    payloads: list[RawIntakePayload] = []
    for file_id in plan.drive_file_ids:
        try:
            payloads.append(fetch_drive_file(file_id=file_id, access_token=access_token, principal=principal))
        except DrivePickerError as exc:
            return _PreconditionFailure(
                provider="google",
                principal=principal,
                detail=f"could not fetch Drive file {file_id!r}: {exc.reason}",
                http_status=status.HTTP_422_UNPROCESSABLE_CONTENT,
            )
    request = IngestionRequest(
        idempotency_scope=plan.idempotency_scope,
        triggered_by=plan.triggered_by,
        household_id=plan.household_id,
        inline_payloads=tuple(payloads),
    )
    return orchestrator.run(request)


def _drive_access_token(
    settings: Settings,
    reader: SecretManagerAdapter,
    credential_store: FirestoreOAuthCredentialStore,
    principal: str,
) -> str | _PreconditionFailure:
    """Mint a `drive.file` access token from the stored Google refresh
    token, or a `_PreconditionFailure` the handler turns into a 409
    reconnect prompt (never a fabricated token, invariant #7)."""
    credential = credential_store.get(OAuthProvider.GOOGLE, principal)
    if credential is None or not credential.is_active:
        return _PreconditionFailure(
            provider="google",
            principal=principal,
            detail="the Google account is not connected",
            http_status=status.HTTP_409_CONFLICT,
        )
    try:
        refresh_token = reader.get_secret_by_resource_name(credential.secret_ref)
        client = get_oauth_client_for("google", settings, reader)
        return client.refresh_access_token(refresh_token).access_token
    except (SecretManagerError, OAuthExchangeFailed, HTTPException) as exc:
        detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
        return _PreconditionFailure(
            provider="google",
            principal=principal,
            detail=f"could not mint a Drive access token (reconnect the account): {detail}",
            http_status=status.HTTP_409_CONFLICT,
        )


def _single_source_precondition(plan: _IngestPlan, result: IngestionRunResult) -> _PreconditionFailure | None:
    """ADR-023 §4: a single-source scan whose only outcome is an
    auth-failure `ConnectorFailure` and which produced zero documents is
    the whole request's precondition failure -> `409`, so E4's
    Connections surface renders a reconnect prompt rather than a bare
    empty run."""
    if len(plan.sources) != 1 or result.outcomes or len(result.connector_failures) != 1:
        return None
    failure = result.connector_failures[0]
    if not failure.is_auth_failure:
        return None
    return _PreconditionFailure(
        provider=_provider_slug_for(failure.source),
        principal=failure.principal or None,
        detail=failure.reason,
        http_status=status.HTTP_409_CONFLICT,
    )


def _provider_slug_for(source: IngestionSourceKind) -> str:
    return "microsoft" if source is IngestionSourceKind.OUTLOOK else "google"


def _serialize_outcome(outcome: DocumentIngestOutcome) -> dict[str, Any]:
    return {
        "content_hash": outcome.content_hash,
        "source": outcome.source.value,
        "status": outcome.status.value,
        "source_document_id": outcome.source_document_id,
        "external_ref": outcome.external_ref,
        "classified_type_id": outcome.classified_type_id,
        "new_node_ids": list(outcome.new_node_ids),
        "new_edge_ids": list(outcome.new_edge_ids),
        "detail": outcome.detail,
    }


def serialize_run_result(result: IngestionRunResult) -> dict[str, Any]:
    """`IngestionRunResult` -> the exact JSON shape
    `frontend/lib/connections.ts::parseIngestionRunResult` narrows.
    Deliberately does not expose any `OAuthCredential.secret_ref` — this
    type never carries one, and the serializer is written so it never
    could."""
    return {
        "run_id": result.run_id,
        "idempotency_scope": result.idempotency_scope,
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "sources_scanned": [s.value for s in result.sources_scanned],
        "outcomes": [_serialize_outcome(o) for o in result.outcomes],
        "new_node_ids": list(result.new_node_ids),
        "connector_failures": [
            {
                "source": f.source.value,
                "principal": f.principal,
                "reason": f.reason,
                "is_auth_failure": f.is_auth_failure,
            }
            for f in result.connector_failures
        ],
        "run_errors": list(result.run_errors),
    }


@router.post("/ingest")
async def ingest(
    request: Request,
    orchestrator: Annotated[IngestionOrchestrator, Depends(get_ingestion_orchestrator)],
    settings: Annotated[Settings, Depends(get_settings)],
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
) -> JSONResponse:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        plan = await _plan_from_multipart(request)
    elif content_type.startswith("application/json") or content_type == "":
        try:
            body = await request.json()
        except ValueError as exc:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"invalid JSON body: {exc}") from exc
        if not isinstance(body, dict):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the JSON body must be an object")
        plan = _plan_from_json(body)
    else:
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            "POST /ingest accepts application/json or multipart/form-data",
        )

    outcome = await run_in_threadpool(
        _execute_plan,
        plan,
        orchestrator=orchestrator,
        settings=settings,
        reader=reader,
        credential_store=credential_store,
    )

    # ADR-023 §4: a whole-request precondition failure (a single-source
    # scan against an account with no valid grant, or a Drive selection
    # with no connected Google account) is a 409 with a connect-the-
    # account body — the orchestrator surfaces the underlying
    # `IngestionError` as a `ConnectorFailure`, and `_execute_plan`
    # promotes the single-source case to a `_PreconditionFailure` here.
    if isinstance(outcome, _PreconditionFailure):
        return JSONResponse(
            status_code=outcome.http_status,
            content={"provider": outcome.provider, "principal": outcome.principal, "detail": outcome.detail},
        )
    logger.info(
        "ingest.run.complete",
        mode=plan.mode,
        run_id=outcome.run_id,
        documents_seen=outcome.documents_seen,
        new_node_count=outcome.new_node_count,
        counts=outcome.counts,
    )
    return JSONResponse(serialize_run_result(outcome))


# ---------------------------------------------------------------------------
# GET /connections
# ---------------------------------------------------------------------------


def _serialize_connection(credential: OAuthCredential) -> dict[str, Any]:
    """`OAuthCredential` MINUS `secret_ref`. Nothing a browser can reach
    ever carries token material or a pointer to it (spec §23, ADR-022)."""
    return {
        "provider": credential.provider.value,
        "principal": credential.principal,
        "granted_scopes": list(credential.granted_scopes),
        "connected_at": credential.connected_at.isoformat(),
        "last_scan_at": credential.last_scan_at.isoformat() if credential.last_scan_at else None,
        "revoked_at": credential.revoked_at.isoformat() if credential.revoked_at else None,
    }


@router.get("/connections")
def list_connections(
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
) -> JSONResponse:
    return JSONResponse([_serialize_connection(c) for c in credential_store.list_active()])


# ---------------------------------------------------------------------------
# POST /connections/{provider}/{principal}/disconnect
# ---------------------------------------------------------------------------


@router.post("/connections/{provider}/{principal}/disconnect")
def disconnect_connection(
    provider: str,
    principal: str,
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    secret_writer: Annotated[SecretManagerWriteAdapter, Depends(get_secret_writer)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
) -> JSONResponse:
    oauth_provider = provider_or_404(provider)
    credential = credential_store.get(oauth_provider, principal)
    if credential is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no connection for {oauth_provider.value}:{principal}",
        )

    revoked_at = datetime.now(UTC)
    _best_effort_provider_revoke(oauth_provider, credential.secret_ref, reader)
    credential_store.mark_revoked(oauth_provider, principal, revoked_at=revoked_at)

    destroyed = 0
    try:
        destroyed = secret_writer.destroy_all_versions(secret_id_from_ref(credential.secret_ref))
    except SecretManagerError as exc:
        logger.error("oauth.disconnect.secret_destroy_failed", provider=oauth_provider.value, error=str(exc))

    logger.info(
        "oauth.disconnect",
        provider=oauth_provider.value,
        principal=principal,
        secret_versions_destroyed=destroyed,
    )
    return JSONResponse(
        {
            "status": "disconnected",
            "provider": oauth_provider.value,
            "principal": principal,
            "revoked_at": revoked_at.isoformat(),
            "secret_versions_destroyed": destroyed,
        }
    )


def _best_effort_provider_revoke(
    provider: OAuthProvider, secret_ref: str, reader: SecretManagerAdapter
) -> None:
    """Google supports programmatic refresh-token revocation (ADR-022 §5);
    Microsoft does not (the record is marked revoked and the user is
    pointed at their account's app-permissions page — the frontend
    handles that copy). Any failure here is logged, never surfaced — the
    credential is still marked revoked and its secret destroyed
    regardless."""
    if provider is not OAuthProvider.GOOGLE:
        return
    try:
        refresh_token = reader.get_secret_by_resource_name(secret_ref)
    except SecretManagerError:
        return
    try:
        with httpx.Client(timeout=httpx.Timeout(10.0)) as client:
            client.post(REVOKE_ENDPOINT, data={"token": refresh_token})
    except httpx.HTTPError as exc:
        logger.warning("oauth.disconnect.google_revoke_failed", error=str(exc))


__all__ = ["DEMO_HOUSEHOLD_ID", "build_ingestion_orchestrator", "router", "serialize_run_result"]
