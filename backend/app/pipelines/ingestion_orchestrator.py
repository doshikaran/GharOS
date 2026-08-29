"""`IngestionOrchestrator` — the one wire from a raw document to committed
graph nodes (ADR-023, DEBT-009's repayment).

`POST /ingest` (and the A67 `ingest.scan_mailbox` voice route) build one
`contracts.ingestion.IngestionRequest` and call `run`. Per source and per
inline payload the orchestrator walks exactly the fixed sequence in
ADR-023 §1:

    normalize -> compute_content_hash -> dedupe check -> store raw bytes
    -> A2 route -> write SOURCE_DOCUMENT -> A3 extract -> A5 entity
    resolution (hard-constraint guard) -> strategy.map_to_graph ->
    GraphWriter.write_node/write_edge -> IngestionDedupeStore.record

One `AuditLog.append(action_type="ingestion_run", ...)` is written BEFORE
any graph node (invariant #2's posture applied to ingestion). Every
failure path produces a real `DocumentIngestOutcome` with a `detail`
string — never a silent drop, never a fabricated success (invariant #7).

Synchronous by design (ADR-023 §2): every stage it sequences is already
sync and blocking; `POST /ingest` offloads `run` to a worker thread.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.errors import AmbiguousEntity, IngestionError, RegistryGap
from contracts.graph_types import (
    AgentId,
    Derivation,
    FieldSchema,
    NodeId,
    Person,
    Provenance,
    SourceDocument,
    SourceRef,
)
from contracts.ingestion import (
    EXTERNAL_IDENTITY_HEADER,
    ConnectorFailure,
    DocumentIngestOutcome,
    DocumentIngestStatus,
    IngestionDedupeStore,
    IngestionRequest,
    IngestionRunResult,
    IngestionSourceKind,
    OAuthCredentialStore,
    OAuthProvider,
    RawIntakePayload,
    SourceConnector,
    compute_content_hash,
)
from contracts.repositories import AuditLog, GraphWriter

from app.adapters import document_type_ids as type_id
from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.document_upload_adapter import DocumentUploadAdapter
from app.adapters.email_adapter import EmailAdapter
from app.adapters.ingestion import (
    INGESTION_SOURCE_KIND_HEADER,
    IngestionAdapter,
    IntakeNormalizationError,
    NormalizedIntake,
)
from app.agents.intake.document_extraction import (
    DocumentExtractionAgent,
    ExtractionRequest,
)
from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.intake.intake_router import IntakeRouter, IntakeRouteResult
from app.persistence.raw_payload_store import RawPayloadStore
from app.reasoning.gemini_client import MediaPart

logger = structlog.get_logger(__name__)

RUN_ACTION_TYPE = "ingestion_run"
_GRAPH_BUILDER_AGENT = AgentId("A7")
_EXTRACTION_AGENT = AgentId("A3")
_SOURCE_DOCUMENT_REGION = "full"

_CHANNEL_EMAIL = "email"
_CHANNEL_DOCUMENT_UPLOAD = "document_upload"

_EMAIL_SOURCE_KINDS = frozenset({IngestionSourceKind.GMAIL, IngestionSourceKind.OUTLOOK})

_HARD_CONSTRAINT_BEARING_TYPES = frozenset(
    {type_id.MEDICAL_DOCUMENT, type_id.PERMISSION_SLIP, type_id.ATTENDANCE_REGISTER}
)
"""Document types whose person mentions decide which household member a
HARD constraint (allergy, custody, signing authority) applies to — A5 is
run with `hard_constraint_context=True` for these, and an unresolved
mention becomes a visible `ENTITY_RESOLUTION_ESCALATED` outcome rather
than a guessed owner (spec §15.2 A5, ADR-023 §1)."""

KnownPeopleProvider = Callable[[], tuple[Person, ...]]


@dataclass(frozen=True, slots=True)
class _Item:
    """One unit of work inside a run: a payload plus the source kind it
    belongs to (a connector's payloads inherit the connector's kind; an
    inline payload reads `INGESTION_SOURCE_KIND_HEADER`)."""

    payload: RawIntakePayload
    source_kind: IngestionSourceKind


class IngestionOrchestrator:
    """The single ingestion entry point's engine. Construct once per
    process at the composition root (dependency-injected, no module-level
    singletons); `run` is safe to call from a worker thread."""

    def __init__(
        self,
        *,
        connectors: Mapping[IngestionSourceKind, SourceConnector],
        dedupe_store: IngestionDedupeStore,
        raw_payload_store: RawPayloadStore,
        intake_router: IntakeRouter,
        extraction_agent: DocumentExtractionAgent,
        entity_resolution_agent: EntityResolutionAgent,
        registry: DocumentTypeRegistry,
        graph_writer: GraphWriter,
        audit_log: AuditLog,
        credential_store: OAuthCredentialStore | None = None,
        known_people_provider: KnownPeopleProvider | None = None,
        normalizers: Mapping[str, IngestionAdapter] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connectors = dict(connectors)
        self._dedupe_store = dedupe_store
        self._raw_payload_store = raw_payload_store
        self._intake_router = intake_router
        self._extraction_agent = extraction_agent
        self._entity_resolution_agent = entity_resolution_agent
        self._registry = registry
        self._graph_writer = graph_writer
        self._audit_log = audit_log
        self._credential_store = credential_store
        self._known_people_provider = known_people_provider or (lambda: ())
        self._normalizers: dict[str, IngestionAdapter] = dict(
            normalizers
            or {
                _CHANNEL_EMAIL: EmailAdapter(),
                _CHANNEL_DOCUMENT_UPLOAD: DocumentUploadAdapter(),
            }
        )
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- public entry --------------------------------------------------

    def run(self, request: IngestionRequest) -> IngestionRunResult:
        run_id = uuid.uuid4().hex
        started_at = self._clock()
        log = logger.bind(run_id=run_id, idempotency_scope=request.idempotency_scope)
        log.info(
            "ingestion.run.start",
            triggered_by=request.triggered_by,
            sources=[s.value for s in request.sources],
            inline_payloads=len(request.inline_payloads),
        )

        run_errors: list[str] = []
        audit_ok = self._write_run_audit(request, run_id, started_at, run_errors, log)
        if not audit_ok:
            # Invariant #2: no graph write without a durable audit record.
            return IngestionRunResult(
                run_id=run_id,
                idempotency_scope=request.idempotency_scope,
                started_at=started_at,
                finished_at=self._clock(),
                sources_scanned=(),
                outcomes=(),
                new_node_ids=(),
                connector_failures=(),
                run_errors=tuple(run_errors),
            )

        items, connector_failures, scanned = self._gather_items(request, log)

        outcomes: list[DocumentIngestOutcome] = []
        for item in items:
            outcomes.append(self._process_item(item, run_id=run_id, log=log))

        self._touch_last_scan(scanned, request.principal)
        new_node_ids = tuple(nid for outcome in outcomes for nid in outcome.new_node_ids)
        finished_at = self._clock()
        result = IngestionRunResult(
            run_id=run_id,
            idempotency_scope=request.idempotency_scope,
            started_at=started_at,
            finished_at=finished_at,
            sources_scanned=tuple(scanned),
            outcomes=tuple(outcomes),
            new_node_ids=new_node_ids,
            connector_failures=tuple(connector_failures),
            run_errors=tuple(run_errors),
        )
        log.info(
            "ingestion.run.finish",
            documents_seen=result.documents_seen,
            new_node_count=result.new_node_count,
            counts=result.counts,
            connector_failures=len(connector_failures),
        )
        return result

    # -- audit -------------------------------------------------------

    def _write_run_audit(
        self,
        request: IngestionRequest,
        run_id: str,
        started_at: datetime,
        run_errors: list[str],
        log: structlog.stdlib.BoundLogger,
    ) -> bool:
        payload: dict[str, str] = {
            "run_id": run_id,
            "idempotency_scope": request.idempotency_scope,
            "triggered_by": request.triggered_by,
            "household_id": request.household_id,
            "sources": ",".join(s.value for s in request.sources),
            "window_seconds": str(int(request.window.total_seconds())) if request.window else "",
            "principal": request.principal or "",
            "inline_payload_count": str(len(request.inline_payloads)),
        }
        try:
            self._audit_log.append(action_type=RUN_ACTION_TYPE, payload=payload, occurred_at=started_at)
            return True
        except Exception as exc:  # noqa: BLE001 - audit failure aborts the run; reported, never hidden
            log.error("ingestion.run.audit_write_failed", error=str(exc))
            run_errors.append(f"audit log append failed: {exc}")
            return False

    # -- gathering -----------------------------------------------------

    def _gather_items(
        self, request: IngestionRequest, log: structlog.stdlib.BoundLogger
    ) -> tuple[list[_Item], list[ConnectorFailure], list[IngestionSourceKind]]:
        items: list[_Item] = []
        failures: list[ConnectorFailure] = []
        scanned: list[IngestionSourceKind] = []

        for source_kind in request.sources:
            connector = self._connectors.get(source_kind)
            if connector is None:
                failures.append(
                    ConnectorFailure(
                        source=source_kind,
                        principal=request.principal or "",
                        reason=f"no connector registered for {source_kind.value}",
                        is_auth_failure=False,
                    )
                )
                continue
            assert request.window is not None and request.principal is not None  # IngestionRequest guarantees
            try:
                fetched: Sequence[RawIntakePayload] = connector.fetch_since(
                    request.window, principal=request.principal
                )
            except IngestionError as exc:
                log.warning("ingestion.run.connector_failed", source=source_kind.value, error=str(exc))
                failures.append(_connector_failure(source_kind, request.principal or "", exc))
                continue
            scanned.append(source_kind)
            items.extend(_Item(payload=payload, source_kind=source_kind) for payload in fetched)

        for payload in request.inline_payloads:
            items.append(_Item(payload=payload, source_kind=_inline_source_kind(payload)))

        return items, failures, scanned

    def _touch_last_scan(self, scanned: list[IngestionSourceKind], principal: str | None) -> None:
        if self._credential_store is None or not principal:
            return
        now = self._clock()
        for source_kind in set(scanned):
            provider = (
                OAuthProvider.GOOGLE if source_kind is IngestionSourceKind.GMAIL else OAuthProvider.MICROSOFT
            )
            try:
                self._credential_store.touch_last_scan(provider, principal, at=now)
            except Exception as exc:  # noqa: BLE001 - a bookkeeping update never fails a run
                logger.warning(
                    "ingestion.run.touch_last_scan_failed", provider=provider.value, error=str(exc)
                )

    # -- per-item pipeline -------------------------------------------

    def _process_item(
        self, item: _Item, *, run_id: str, log: structlog.stdlib.BoundLogger
    ) -> DocumentIngestOutcome:
        payload = item.payload
        source_kind = item.source_kind
        external_ref = payload.headers.get(EXTERNAL_IDENTITY_HEADER)
        item_log = log.bind(source=source_kind.value, external_ref=external_ref)
        try:
            return self._run_stages(item, external_ref, run_id, item_log)
        except Exception as exc:  # noqa: BLE001 - per-document boundary (ADR-023 §4); ERROR outcome, never a drop
            item_log.exception("ingestion.item.unexpected_error")
            content_hash = _best_effort_hash(source_kind, payload)
            return _outcome(
                content_hash=content_hash,
                source=source_kind,
                status=DocumentIngestStatus.ERROR,
                source_document_id=None,
                external_ref=external_ref,
                classified_type_id=None,
                detail=f"unexpected {type(exc).__name__} at ingestion stage: {exc}",
            )

    def _run_stages(
        self,
        item: _Item,
        external_ref: str | None,
        run_id: str,
        item_log: structlog.stdlib.BoundLogger,
    ) -> DocumentIngestOutcome:
        payload = item.payload
        source_kind = item.source_kind
        channel = _channel_for(source_kind)
        normalizer = self._normalizers[channel]

        # normalize first: `compute_content_hash`'s `text_content` argument
        # is contractually `NormalizedIntake.text_content` (contracts.
        # ingestion item 6). "before any stage runs" (ADR-023 §1) means
        # before A2/A3/A5/map/write — normalization is an adapter step, not
        # a pipeline stage.
        try:
            normalized = normalizer.normalize(payload)
        except IntakeNormalizationError as exc:
            item_log.warning("ingestion.item.normalization_failed", error=str(exc))
            return _outcome(
                content_hash=_best_effort_hash(source_kind, payload),
                source=source_kind,
                status=DocumentIngestStatus.ERROR,
                source_document_id=None,
                external_ref=external_ref,
                classified_type_id=None,
                detail=f"normalization failed: {exc}",
            )

        content_hash = compute_content_hash(
            source_kind=source_kind,
            external_identity=external_ref or "",
            media_type=payload.media_type,
            raw_bytes=payload.binary,
            text_content=normalized.text_content,
        )
        item_log = item_log.bind(content_hash=content_hash)

        seen = self._dedupe_store.seen(content_hash)
        if seen is not None:
            item_log.info("ingestion.item.duplicate_skipped", original_source_document_id=seen)
            return _outcome(
                content_hash=content_hash,
                source=source_kind,
                status=DocumentIngestStatus.DUPLICATE_SKIPPED,
                source_document_id=seen,
                external_ref=external_ref,
                classified_type_id=None,
                detail="content hash matched a prior ingest; nothing written",
            )

        raw_ref = self._raw_payload_store.store(
            payload.binary if payload.binary is not None else (payload.text or "").encode("utf-8"),
            content_type=payload.media_type or "application/octet-stream",
        )

        route = self._intake_router.route(normalized)
        item_log.info(
            "ingestion.item.routed",
            resolved=route.resolved,
            classified_type_id=route.classified_type_id,
            type_confidence=route.type_confidence,
        )
        source_document_id = self._write_source_document(normalized, raw_ref, route)

        if not route.resolved:
            detail = (
                route.registry_gap.detection_summary
                if route.registry_gap is not None
                else "A2 could not resolve a registered document type"
            )
            item_log.warning("ingestion.item.registry_gap", detail=detail)
            return _outcome(
                content_hash=content_hash,
                source=source_kind,
                status=DocumentIngestStatus.REGISTRY_GAP,
                source_document_id=str(source_document_id),
                external_ref=external_ref,
                classified_type_id=None,
                detail=detail,
                new_node_ids=(str(source_document_id),),
            )

        assert route.classified_type_id is not None  # route.resolved guarantees it
        try:
            spec, strategy = self._registry.resolve(route.classified_type_id)
        except RegistryGap as gap:
            return _outcome(
                content_hash=content_hash,
                source=source_kind,
                status=DocumentIngestStatus.REGISTRY_GAP,
                source_document_id=str(source_document_id),
                external_ref=external_ref,
                classified_type_id=route.classified_type_id,
                detail=str(gap),
                new_node_ids=(str(source_document_id),),
            )

        extraction = self._extraction_agent.extract(
            _build_extraction_request(
                source_document_id,
                route.classified_type_id,
                spec.field_schema,
                normalized,
                item.payload,
            )
        )
        usable_fields = tuple(
            field for field in extraction.extracted_fields if field.derivation is not Derivation.AMBIGUOUS
        )
        if not usable_fields:
            detail = (
                f"all {len(extraction.extracted_fields)} extracted field(s) fell below the type's "
                f"confidence floor; fields_not_found={list(extraction.fields_not_found)}"
            )
            item_log.warning("ingestion.item.extraction_failed", detail=detail)
            return _outcome(
                content_hash=content_hash,
                source=source_kind,
                status=DocumentIngestStatus.EXTRACTION_FAILED,
                source_document_id=str(source_document_id),
                external_ref=external_ref,
                classified_type_id=route.classified_type_id,
                detail=detail,
                new_node_ids=(str(source_document_id),),
            )

        escalation = self._entity_resolution_guard(route.classified_type_id, normalized, item_log)
        if escalation is not None:
            return _outcome(
                content_hash=content_hash,
                source=source_kind,
                status=DocumentIngestStatus.ENTITY_RESOLUTION_ESCALATED,
                source_document_id=str(source_document_id),
                external_ref=external_ref,
                classified_type_id=route.classified_type_id,
                detail=escalation,
                new_node_ids=(str(source_document_id),),
            )

        mapping = strategy.map_to_graph(
            source_document_id=source_document_id,
            extracted_fields=extraction.extracted_fields,
            deriving_agent=_EXTRACTION_AGENT,
        )
        new_node_ids: list[str] = [str(source_document_id)]
        new_edge_ids: list[str] = []
        for node in mapping.nodes:
            new_node_ids.append(str(self._graph_writer.write_node(node)))
        for edge in mapping.edges:
            self._graph_writer.write_edge(edge)
            new_edge_ids.append(str(edge.id))

        self._dedupe_store.record(
            content_hash,
            source_document_id=str(source_document_id),
            run_id=run_id,
            ingested_at=self._clock(),
        )
        item_log.info(
            "ingestion.item.ingested",
            classified_type_id=route.classified_type_id,
            new_node_count=len(new_node_ids),
            new_edge_count=len(new_edge_ids),
            verification_findings=list(mapping.verification_findings),
        )
        return _outcome(
            content_hash=content_hash,
            source=source_kind,
            status=DocumentIngestStatus.INGESTED,
            source_document_id=str(source_document_id),
            external_ref=external_ref,
            classified_type_id=route.classified_type_id,
            detail="; ".join(mapping.verification_findings),
            new_node_ids=tuple(new_node_ids),
            new_edge_ids=tuple(new_edge_ids),
        )

    # -- stage helpers ----------------------------------------------

    def _write_source_document(
        self, normalized: NormalizedIntake, raw_ref: str, route: IntakeRouteResult
    ) -> NodeId:
        now = self._clock()
        doc_id = NodeId(f"doc:{uuid.uuid4().hex}")
        confidence = route.type_confidence if 0.0 <= route.type_confidence <= 1.0 else 1.0
        document = SourceDocument(
            id=doc_id,
            provenance=Provenance(
                derivation=Derivation.EXTRACTED,
                source_ref=SourceRef(source_document_id=doc_id, region=_SOURCE_DOCUMENT_REGION),
                confidence=confidence,
                deriving_agent=_GRAPH_BUILDER_AGENT,
                created_at=now,
            ),
            channel=normalized.channel,
            raw_payload_ref=raw_ref,
            document_type=route.classified_type_id,
            ingested_at=normalized.received_at,
            original_language=normalized.original_language_hint,
        )
        return self._graph_writer.write_node(document)

    def _entity_resolution_guard(
        self,
        classified_type_id: str,
        normalized: NormalizedIntake,
        item_log: structlog.stdlib.BoundLogger,
    ) -> str | None:
        """Runs A5 for a hard-constraint-bearing document's sender mention.
        Returns an escalation detail string when A5 raises
        `AmbiguousEntity(hard_constraint_bearing=True)`, else `None`
        (resolution is advisory context this phase — ADR-023 §5)."""
        if classified_type_id not in _HARD_CONSTRAINT_BEARING_TYPES:
            return None
        mention = normalized.sender
        if not mention:
            return None
        known_people = self._known_people_provider()
        try:
            result = self._entity_resolution_agent.resolve(
                mention_text=mention,
                mention_context=(normalized.text_content or "")[:400],
                known_people=known_people,
                hard_constraint_context=True,
            )
        except AmbiguousEntity as exc:
            if not exc.hard_constraint_bearing:
                return None
            return (
                f"A5 could not resolve hard-constraint-bearing mention {exc.mention!r} to a single "
                f"PERSON node; candidates={list(exc.candidates)}. Escalated with the document; no "
                f"typed owner written (spec §15.2 A5)."
            )
        item_log.info(
            "ingestion.item.entity_resolution",
            mention=mention,
            resolution=result.resolution.value,
            matched_person_id=str(result.matched_person_id) if result.matched_person_id else None,
        )
        return None


# ---------------------------------------------------------------------------
# Module-level pure helpers
# ---------------------------------------------------------------------------


def _channel_for(source_kind: IngestionSourceKind) -> str:
    return _CHANNEL_EMAIL if source_kind in _EMAIL_SOURCE_KINDS else _CHANNEL_DOCUMENT_UPLOAD


def _inline_source_kind(payload: RawIntakePayload) -> IngestionSourceKind:
    raw = payload.headers.get(INGESTION_SOURCE_KIND_HEADER)
    if raw == IngestionSourceKind.DRIVE_PICKER.value:
        return IngestionSourceKind.DRIVE_PICKER
    return IngestionSourceKind.DIRECT_UPLOAD


def _best_effort_hash(source_kind: IngestionSourceKind, payload: RawIntakePayload) -> str:
    """A content hash for an item that failed before normalization — uses
    the RAW text so the `DocumentIngestOutcome.content_hash` field is
    always populated (contract requirement), accepting that it will not
    match a later successful ingest of a cleaned-up version of the same
    item (that later ingest is genuinely new)."""
    return compute_content_hash(
        source_kind=source_kind,
        external_identity=payload.headers.get(EXTERNAL_IDENTITY_HEADER) or "",
        media_type=payload.media_type,
        raw_bytes=payload.binary,
        text_content=payload.text,
    )


def _build_extraction_request(
    source_document_id: NodeId,
    classified_type_id: str,
    field_schema: tuple[FieldSchema, ...],
    normalized: NormalizedIntake,
    payload: RawIntakePayload,
) -> ExtractionRequest:
    if payload.binary is not None and normalized.text_content is None:
        return ExtractionRequest(
            source_document_id=source_document_id,
            type_id=classified_type_id,
            field_schema=field_schema,
            text_content=None,
            media=(MediaPart(data=payload.binary, mime_type=payload.media_type),),
        )
    return ExtractionRequest(
        source_document_id=source_document_id,
        type_id=classified_type_id,
        field_schema=field_schema,
        text_content=normalized.text_content or "",
        media=(),
    )


def _connector_failure(
    source_kind: IngestionSourceKind, principal: str, exc: IngestionError
) -> ConnectorFailure:
    from contracts.errors import (
        OAuthConnectionRequired,
        OAuthScopeInsufficient,
        OAuthTokenRefreshFailed,
    )

    is_auth = isinstance(exc, (OAuthConnectionRequired, OAuthScopeInsufficient, OAuthTokenRefreshFailed))
    return ConnectorFailure(
        source=source_kind,
        principal=principal,
        reason=str(exc),
        is_auth_failure=is_auth,
    )


def _outcome(
    *,
    content_hash: str,
    source: IngestionSourceKind,
    status: DocumentIngestStatus,
    source_document_id: str | None,
    external_ref: str | None,
    classified_type_id: str | None,
    detail: str,
    new_node_ids: tuple[str, ...] = (),
    new_edge_ids: tuple[str, ...] = (),
) -> DocumentIngestOutcome:
    return DocumentIngestOutcome(
        content_hash=content_hash,
        source=source,
        status=status,
        source_document_id=source_document_id,
        external_ref=external_ref,
        classified_type_id=classified_type_id,
        new_node_ids=new_node_ids,
        new_edge_ids=new_edge_ids,
        detail=detail,
    )


__all__ = ["IngestionOrchestrator", "RUN_ACTION_TYPE"]
