"""End-to-end integration test for `IngestionOrchestrator` (ADR-023,
DEBT-009's repayment).

Runs the REAL orchestrator against the REAL Firestore emulator: a fake
`SourceConnector` feeds a real email body, and the pipeline routes,
extracts, maps, and commits real graph nodes through the real
provenance-guarded `FirestoreGraphWriter`. Only the Gemini calls (A2 /
A3) are faked, via the established `_gemini_fakes` queue.

Covers Gate 14.5's honest-outcome requirements: a real document produces
real provenance-linked nodes; a re-scan of the same window writes zero
new nodes (`duplicate_skipped`); a failed extraction is a visible
`extraction_failed`; an unclassifiable document is a visible
`registry_gap`; and a failed run-audit write blocks every graph write
(invariant #2).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from contracts.graph_types import (
    AgentId,
    DocumentTypeSpec,
    ExtractedField,
    FieldSchema,
    GraphMappingResult,
    NodeId,
    Provenance,
    SourceDocument,
    SourceRef,
    Vendor,
)
from contracts.ingestion import (
    EXTERNAL_IDENTITY_HEADER,
    DocumentIngestStatus,
    IngestionRequest,
    IngestionSourceKind,
    RawIntakePayload,
)
from contracts.repositories import AuditLog
from google.cloud import firestore

from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake.document_extraction import DocumentExtractionAgent
from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies import register_all_strategies
from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.ingestion_dedupe_store import create_ingestion_dedupe_store
from app.pipelines.ingestion_orchestrator import RUN_ACTION_TYPE, IngestionOrchestrator
from app.reasoning.gemini_client import GeminiClient

from ._fake_raw_payload_store import FakeRawPayloadStore
from ._gemini_fakes import FakeModels, fake_router
from ._ingestion_fakes import FakeSourceConnector

_TYPE_ID = "delivery_confirmation"
_EMAIL_BODY = "Your parcel via BlueDart, tracking BD123456789, was delivered today. Thank you."


def _spec() -> DocumentTypeSpec:
    return DocumentTypeSpec(
        type_id=_TYPE_ID,
        detection_signals=("courier_name", "tracking_number", "delivery_language"),
        field_schema=(
            FieldSchema(name="courier", field_type="string", required=True, confidence_floor=0.60),
            FieldSchema(name="tracking_number", field_type="string", required=True, confidence_floor=0.60),
        ),
        target_node_types=("VENDOR",),
        target_edge_types=(),
        downstream_subsystems=("ledger",),
        verification_duties=("delivery_confirmation",),
    )


class _Strategy:
    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        courier = next(f for f in extracted_fields if f.name == "courier")
        vendor = Vendor(
            id=NodeId(f"vendor:{courier.value}"),
            provenance=Provenance(
                derivation=courier.derivation,
                source_ref=SourceRef(source_document_id=source_document_id, region=courier.source_region),
                confidence=courier.confidence,
                deriving_agent=deriving_agent,
                created_at=datetime.now(UTC),
            ),
            category="courier",
            contacts=(),
            reliability_score=None,
            response_latency_hours=None,
        )
        return GraphMappingResult(nodes=(vendor,), edges=())


_CLASSIFY_OK: dict[str, object] = {
    "type_id": _TYPE_ID,
    "type_confidence": 0.93,
    "signals_matched": ["courier_name", "tracking_number"],
    "runner_up_type_id": None,
    "runner_up_confidence": 0.0,
    "relevance": "relevant",
    "relevance_reason": "A courier delivery confirmation.",
}
_CLASSIFY_UNRESOLVED: dict[str, object] = {
    "type_id": None,
    "type_confidence": 0.0,
    "signals_matched": [],
    "runner_up_type_id": None,
    "runner_up_confidence": 0.0,
    "relevance": "relevant",
    "relevance_reason": "No recognisable document structure.",
}
_EXTRACT_OK: dict[str, object] = {
    "fields": [
        {"name": "courier", "value": "BlueDart", "confidence": 0.9, "region": "13-21"},
        {"name": "tracking_number", "value": "BD123456789", "confidence": 0.9, "region": "31-42"},
    ],
    "fields_not_found": [],
    "degraded_input_observed": False,
}
_EXTRACT_EMPTY: dict[str, object] = {
    "fields": [],
    "fields_not_found": ["courier", "tracking_number"],
    "degraded_input_observed": False,
}


class _FailingAuditLog:
    def append(self, *, action_type: str, payload: dict[str, str], occurred_at: datetime) -> str:
        raise RuntimeError("audit backend unavailable")


def _payload(external_id: str, *, body: str = _EMAIL_BODY) -> RawIntakePayload:
    return RawIntakePayload(
        text=body,
        binary=None,
        media_type="text/plain",
        headers={EXTERNAL_IDENTITY_HEADER: external_id, "from": "noreply@bluedart.example"},
        received_at=datetime(2026, 8, 29, 9, 0, tzinfo=UTC),
    )


def _fake_gemini(response: dict[str, object]) -> GeminiClient:
    return GeminiClient(router=fake_router(FakeModels(texts=[json.dumps(response)])))


def _orchestrator(
    firestore_client: firestore.Client,
    *,
    connector: FakeSourceConnector,
    classification: dict[str, object],
    extraction: dict[str, object],
    audit_log: AuditLog | None = None,
) -> IngestionOrchestrator:
    registry = DocumentTypeRegistry()
    register_all_strategies(registry)
    registry.register(_TYPE_ID, _spec(), _Strategy())
    store = FirestoreGraphStore(firestore_client)
    return IngestionOrchestrator(
        connectors={IngestionSourceKind.GMAIL: connector},
        dedupe_store=create_ingestion_dedupe_store(firestore_client),
        raw_payload_store=FakeRawPayloadStore(),
        intake_router=IntakeRouter(
            gemini_client=_fake_gemini(classification),
            registry=registry,
            gap_log=RegistryGapLog(InMemoryRegistryGapStore()),
        ),
        extraction_agent=DocumentExtractionAgent(gemini_client=_fake_gemini(extraction)),
        entity_resolution_agent=EntityResolutionAgent(gemini_client=_fake_gemini({})),
        registry=registry,
        graph_writer=FirestoreGraphWriter(store),
        audit_log=audit_log or FirestoreAuditLog(firestore_client),
    )


def _request(scope: str = "test-run:1") -> IngestionRequest:
    return IngestionRequest(
        idempotency_scope=scope,
        triggered_by="test",
        household_id="gharos-demo-household",
        sources=(IngestionSourceKind.GMAIL,),
        window=timedelta(hours=24),
        principal="alice@example.com",
    )


# ---------------------------------------------------------------------------


def test_one_real_document_produces_provenance_linked_graph_nodes(
    firestore_client: firestore.Client,
) -> None:
    connector = FakeSourceConnector(IngestionSourceKind.GMAIL, [_payload("m-real-1")])
    orchestrator = _orchestrator(
        firestore_client, connector=connector, classification=_CLASSIFY_OK, extraction=_EXTRACT_OK
    )

    result = orchestrator.run(_request())

    assert result.counts[DocumentIngestStatus.INGESTED.value] == 1
    outcome = result.outcomes[0]
    assert outcome.status is DocumentIngestStatus.INGESTED
    assert outcome.classified_type_id == _TYPE_ID
    assert outcome.source_document_id is not None

    reader = FirestoreGraphReader(FirestoreGraphStore(firestore_client))
    source_document = reader.get_node(NodeId(outcome.source_document_id))
    assert isinstance(source_document, SourceDocument)
    assert source_document.document_type == _TYPE_ID
    assert source_document.channel == "email"

    vendor_ids = [nid for nid in outcome.new_node_ids if nid.startswith("vendor:")]
    assert len(vendor_ids) == 1
    vendor = reader.get_node(NodeId(vendor_ids[0]))
    assert isinstance(vendor, Vendor)
    # Invariant #3: the derived node's provenance points back to the
    # SOURCE_DOCUMENT the wire wrote — queryable end to end.
    assert vendor.provenance.source_ref is not None
    assert str(vendor.provenance.source_ref.source_document_id) == outcome.source_document_id

    audit_records = FirestoreAuditLog(firestore_client).all_records()
    assert any(r.action_type == RUN_ACTION_TYPE for r in audit_records)


def test_rescanning_the_same_window_writes_zero_new_nodes(firestore_client: firestore.Client) -> None:
    payloads = [_payload("m-dup-1")]
    first = _orchestrator(
        firestore_client,
        connector=FakeSourceConnector(IngestionSourceKind.GMAIL, payloads),
        classification=_CLASSIFY_OK,
        extraction=_EXTRACT_OK,
    ).run(_request("scan:first"))
    assert first.counts[DocumentIngestStatus.INGESTED.value] == 1

    second = _orchestrator(
        firestore_client,
        connector=FakeSourceConnector(IngestionSourceKind.GMAIL, payloads),
        classification=_CLASSIFY_OK,
        extraction=_EXTRACT_OK,
    ).run(_request("scan:second"))

    assert second.new_node_ids == ()
    assert second.counts[DocumentIngestStatus.DUPLICATE_SKIPPED.value] == 1
    assert second.counts[DocumentIngestStatus.INGESTED.value] == 0
    # points at the ORIGINAL source document, not a new one
    assert second.outcomes[0].source_document_id == first.outcomes[0].source_document_id


def test_failed_extraction_is_a_visible_outcome_not_a_silent_drop(
    firestore_client: firestore.Client,
) -> None:
    connector = FakeSourceConnector(IngestionSourceKind.GMAIL, [_payload("m-extract-fail")])
    result = _orchestrator(
        firestore_client, connector=connector, classification=_CLASSIFY_OK, extraction=_EXTRACT_EMPTY
    ).run(_request("scan:extract-fail"))

    outcome = result.outcomes[0]
    assert outcome.status is DocumentIngestStatus.EXTRACTION_FAILED
    assert outcome.source_document_id is not None  # SOURCE_DOCUMENT retained
    assert outcome.new_node_ids == (outcome.source_document_id,)
    assert outcome.detail  # a real reason string, never empty


def test_unclassifiable_document_is_a_visible_registry_gap(firestore_client: firestore.Client) -> None:
    connector = FakeSourceConnector(IngestionSourceKind.GMAIL, [_payload("m-gap-1")])
    result = _orchestrator(
        firestore_client,
        connector=connector,
        classification=_CLASSIFY_UNRESOLVED,
        extraction=_EXTRACT_OK,
    ).run(_request("scan:gap"))

    outcome = result.outcomes[0]
    assert outcome.status is DocumentIngestStatus.REGISTRY_GAP
    assert outcome.source_document_id is not None
    assert result.counts[DocumentIngestStatus.REGISTRY_GAP.value] == 1


def test_audit_write_failure_blocks_every_graph_write(firestore_client: firestore.Client) -> None:
    connector = FakeSourceConnector(IngestionSourceKind.GMAIL, [_payload("m-audit-fail")])
    orchestrator = _orchestrator(
        firestore_client,
        connector=connector,
        classification=_CLASSIFY_OK,
        extraction=_EXTRACT_OK,
        audit_log=_FailingAuditLog(),
    )

    result = orchestrator.run(_request("scan:audit-fail"))

    # Invariant #2: no graph write without a durable audit record.
    assert result.new_node_ids == ()
    assert result.outcomes == ()
    assert result.run_errors and "audit" in result.run_errors[0].lower()
    assert connector.calls == []  # the run aborts before the connector is even asked to fetch


@pytest.mark.parametrize("is_auth", [True, False])
def test_connector_failure_is_run_data_never_raised(
    firestore_client: firestore.Client, is_auth: bool
) -> None:
    from contracts.errors import ConnectorFetchFailed, OAuthTokenRefreshFailed

    exc: Exception = (
        OAuthTokenRefreshFailed(provider="google", principal="alice@example.com", reason="revoked")
        if is_auth
        else ConnectorFetchFailed(
            provider="google", principal="alice@example.com", reason="503 x3", retryable=True
        )
    )
    connector = FakeSourceConnector(IngestionSourceKind.GMAIL, [], raises=exc)
    result = _orchestrator(
        firestore_client, connector=connector, classification=_CLASSIFY_OK, extraction=_EXTRACT_OK
    ).run(_request("scan:connector-fail"))

    assert result.outcomes == ()
    assert len(result.connector_failures) == 1
    assert result.connector_failures[0].is_auth_failure is is_auth
