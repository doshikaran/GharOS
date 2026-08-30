"""DEBT-004 strike proof — a photographed handwritten **attendance
register** run through the REAL `IngestionOrchestrator` (`POST /ingest`'s
engine, ADR-023) against the REAL Firestore emulator produces a real,
graph-written `AttendanceRecord` node with provenance tracing back to the
`SOURCE_DOCUMENT` the wire created, the salary-payment `Obligation` it
feeds plus the `implies` edge anchoring that obligation to the register,
and its `attendance_of` edge to a pre-resolved staff `Person` — leaving
the graph integrity-checker-clean.

The write comes from the **production** `ExtractionStrategy`,
`app.agents.intake.strategies.attendance_register_strategy.
AttendanceRegisterExtractionStrategy` (no test-local reference strategy):
its `map_to_graph` now builds the `AttendanceRecord` / salary `Obligation`
/ `implies` edge for real (ADR-013), and — given an optional injected
`staff_index` (the same additive constructor arg the registry ignores) —
the `attendance_of` edge too. Only the Gemini calls (A2 classify, A3
extract) are faked, via the established `_gemini_fakes` queue; every other
stage is the production object: `IntakeRouter`, `DocumentExtractionAgent`,
the real `_attendance_register_spec` (strictest confidence floors in the
registry), `FirestoreGraphWriter` (provenance guard), `FirestoreAuditLog`,
the real Firestore dedupe store.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    AttendanceRecord,
    Derivation,
    EdgeType,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Person,
    PersonRole,
    Provenance,
    SourceDocument,
    SourceRef,
)
from contracts.ingestion import (
    DocumentIngestStatus,
    IngestionRequest,
    RawIntakePayload,
)
from google.cloud import firestore

from app.adapters import document_type_ids as type_id
from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.document_type_specs import DOCUMENT_TYPE_SPECS_BY_ID
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake.document_extraction import DocumentExtractionAgent
from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.strategies.attendance_register_strategy import (
    AttendanceRegisterExtractionStrategy,
)
from app.audit.audit_log import FirestoreAuditLog
from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.ingestion_dedupe_store import create_ingestion_dedupe_store
from app.pipelines.ingestion_orchestrator import RUN_ACTION_TYPE, IngestionOrchestrator
from app.reasoning.gemini_client import GeminiClient

from ._fake_raw_payload_store import FakeRawPayloadStore
from ._gemini_fakes import FakeModels, fake_router

_STAFF_PERSON_ID = NodeId("person-salim")
_FAKE_JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF" + b"handwritten-attendance-grid" * 4

_CLASSIFY_ATTENDANCE: dict[str, object] = {
    "type_id": type_id.ATTENDANCE_REGISTER,
    "type_confidence": 0.95,
    "signals_matched": ["grid_tabular_structure", "date_column", "name_rows", "tick_or_cross_marks"],
    "runner_up_type_id": None,
    "runner_up_confidence": 0.0,
    "relevance": "relevant",
    "relevance_reason": "A handwritten monthly staff attendance grid.",
}

# Every confidence is >= this type's floor (staff_member 0.92 / month 0.90 /
# per_day_presence_marks 0.95) so A3 tags them EXTRACTED, not AMBIGUOUS.
_EXTRACT_ATTENDANCE: dict[str, object] = {
    "fields": [
        {"name": "staff_member", "value": "Salim", "confidence": 0.97, "region": "page=1;bbox=12,20,180,44"},
        {"name": "month", "value": "2026-08", "confidence": 0.98, "region": "page=1;bbox=190,20,320,44"},
        {
            "name": "per_day_presence_marks",
            "value": [
                {"day": "01", "mark": "present"},
                {"day": "02", "mark": "present"},
                {"day": "03", "mark": "present"},
                {"day": "04", "mark": "absent"},
                {"day": "05", "mark": "present"},
                {"day": "06", "mark": "leave"},
                {"day": "07", "mark": "present"},
                {"day": "08", "mark": "present"},
            ],
            "confidence": 0.96,
            "region": "page=1;bbox=12,50,900,320",
        },
        {
            "name": "leave_annotations",
            "value": ["06 Aug - family function"],
            "confidence": 0.95,
            "region": "page=1;bbox=12,330,900,360",
        },
        {
            "name": "advance_notations_margin",
            "value": ["hasil 3000 - 14 tarikh"],
            "confidence": 0.95,
            "region": "page=1;bbox=905,50,980,320",
        },
    ],
    "fields_not_found": [],
    "degraded_input_observed": False,
}


def _fake_gemini(response: dict[str, object]) -> GeminiClient:
    return GeminiClient(router=fake_router(FakeModels(texts=[json.dumps(response)])))


def _seed_staff_person(store: FirestoreGraphStore) -> None:
    """A real staff PERSON, written through the real provenance guard, so
    the `attendance_of` edge resolves and the integrity checker stays
    clean — the entity-resolution table the production strategy consults
    via its optional injected `staff_index`."""
    FirestoreGraphWriter(store).write_node(
        Person(
            id=_STAFF_PERSON_ID,
            provenance=Provenance(
                derivation=Derivation.EXTRACTED,
                source_ref=SourceRef(source_document_id=NodeId("doc-staff-onboarding"), region="1-20"),
                confidence=0.95,
                deriving_agent=AgentId("A7"),
                created_at=datetime(2026, 6, 1, tzinfo=UTC),
            ),
            display_name="Salim",
            aliases=("Salim Bhai",),
            role=PersonRole.STAFF,
            can_drive=True,
            can_sign=False,
            has_bank_access=False,
            has_medical_proxy=False,
            contact_channels=("voice:+91-90000-00006",),
            language_profile=LanguageProfile(
                primary_language="hi",
                languages_understood=("hi", "en"),
                script_preference="devanagari",
                code_mixing_profile="hi-en",
                formality_preference="informal",
                literacy_mode=LiteracyMode.BOTH,
            ),
        )
    )


def _orchestrator(firestore_client: firestore.Client) -> IngestionOrchestrator:
    registry = DocumentTypeRegistry()
    registry.register(
        type_id.ATTENDANCE_REGISTER,
        DOCUMENT_TYPE_SPECS_BY_ID[type_id.ATTENDANCE_REGISTER],
        # The production strategy, constructed exactly as the registry
        # constructs it plus the additive optional `staff_index` an
        # ingestion caller with a resolved roster may supply.
        AttendanceRegisterExtractionStrategy(staff_index={"Salim": _STAFF_PERSON_ID}),
    )
    store = FirestoreGraphStore(firestore_client)
    return IngestionOrchestrator(
        connectors={},
        dedupe_store=create_ingestion_dedupe_store(firestore_client),
        raw_payload_store=FakeRawPayloadStore(),
        intake_router=IntakeRouter(
            gemini_client=_fake_gemini(_CLASSIFY_ATTENDANCE),
            registry=registry,
            gap_log=RegistryGapLog(InMemoryRegistryGapStore()),
        ),
        extraction_agent=DocumentExtractionAgent(gemini_client=_fake_gemini(_EXTRACT_ATTENDANCE)),
        entity_resolution_agent=EntityResolutionAgent(gemini_client=_fake_gemini({})),
        registry=registry,
        graph_writer=FirestoreGraphWriter(store),
        audit_log=FirestoreAuditLog(firestore_client),
    )


def _register_payload() -> RawIntakePayload:
    return RawIntakePayload(
        text=None,
        binary=_FAKE_JPEG,
        media_type="image/jpeg",
        headers={"filename": "salim-attendance-register-2026-08.jpg"},
        received_at=datetime(2026, 9, 1, 9, 0, tzinfo=UTC),
    )


def _request() -> IngestionRequest:
    return IngestionRequest(
        idempotency_scope="debt-004:attendance-register:1",
        triggered_by="manual",
        household_id="gharos-demo-household",
        inline_payloads=(_register_payload(),),
    )


def test_photographed_register_through_the_wire_writes_a_real_attendance_record(
    firestore_client: firestore.Client,
) -> None:
    store = FirestoreGraphStore(firestore_client)
    _seed_staff_person(store)

    result = _orchestrator(firestore_client).run(_request())

    assert result.counts[DocumentIngestStatus.INGESTED.value] == 1
    outcome = result.outcomes[0]
    assert outcome.status is DocumentIngestStatus.INGESTED
    assert outcome.classified_type_id == type_id.ATTENDANCE_REGISTER
    assert outcome.source_document_id is not None

    reader = FirestoreGraphReader(store)

    source_document = reader.get_node(NodeId(outcome.source_document_id))
    assert isinstance(source_document, SourceDocument)
    assert source_document.document_type == type_id.ATTENDANCE_REGISTER
    assert source_document.channel == "document_upload"

    attendance_ids = [nid for nid in outcome.new_node_ids if nid.startswith("attendance:")]
    assert len(attendance_ids) == 1, outcome.new_node_ids
    record = reader.get_node(NodeId(attendance_ids[0]))
    assert isinstance(record, AttendanceRecord)

    # Real extracted content, not a hand-constructed fixture:
    assert record.month == "2026-08"
    assert record.daily_marks["04"] == "absent"
    assert record.daily_marks["06"] == "leave"
    assert record.days_present == 6
    assert record.days_absent == 1
    assert record.days_on_leave == 1
    assert record.total_days_in_period == 8
    assert record.advance_notations == ("hasil 3000 - 14 tarikh",)

    # Invariant #3: provenance traces to the SOURCE_DOCUMENT the wire wrote.
    assert record.provenance.source_ref is not None
    assert str(record.provenance.source_ref.source_document_id) == outcome.source_document_id
    assert record.provenance.derivation is Derivation.EXTRACTED

    # attendance_of -> the pre-resolved staff PERSON, walkable.
    assert record.staff_person_id == _STAFF_PERSON_ID
    staff_neighbours = reader.neighbours(record.id, EdgeType.ATTENDANCE_OF)
    assert [n.id for n in staff_neighbours if isinstance(n, Person)] == [_STAFF_PERSON_ID]

    # The salary-payment Obligation the register feeds (spec §5.4.2 / §10.3)
    # plus the `implies` edge anchoring it to the SOURCE_DOCUMENT (ADR-013 —
    # no direct SOURCE_DOCUMENT -> ATTENDANCE_RECORD edge type exists).
    implied = reader.neighbours(NodeId(outcome.source_document_id), EdgeType.IMPLIES)
    salary_obligations = [
        n
        for n in implied
        if isinstance(n, Obligation) and n.obligation_type == "payment" and "Salim" in n.title
    ]
    assert len(salary_obligations) == 1, implied
    salary = salary_obligations[0]
    assert salary.stated_or_implied is ObligationDerivation.IMPLIED
    assert salary.status is ObligationStatus.DERIVED
    assert salary.provenance.derivation is Derivation.INFERRED
    assert salary.provenance.source_ref is not None
    assert str(salary.provenance.source_ref.source_document_id) == outcome.source_document_id
    assert str(salary.id) in outcome.new_node_ids
    assert any(eid.startswith("edge:implies:") for eid in outcome.new_edge_ids)
    assert any(eid.startswith("edge:attendance_of:") for eid in outcome.new_edge_ids)

    # Audit-before-write (invariant #2) and a clean graph after.
    audit_records = FirestoreAuditLog(firestore_client).all_records()
    assert any(r.action_type == RUN_ACTION_TYPE for r in audit_records)
    assert FirestoreGraphIntegrityChecker(store).check("all") == ()


def test_rerunning_the_same_register_writes_no_duplicate_attendance_record(
    firestore_client: firestore.Client,
) -> None:
    store = FirestoreGraphStore(firestore_client)
    _seed_staff_person(store)

    first = _orchestrator(firestore_client).run(_request())
    assert first.counts[DocumentIngestStatus.INGESTED.value] == 1

    second = _orchestrator(firestore_client).run(
        IngestionRequest(
            idempotency_scope="debt-004:attendance-register:2",
            triggered_by="manual",
            household_id="gharos-demo-household",
            inline_payloads=(_register_payload(),),
        )
    )
    assert second.new_node_ids == ()
    assert second.counts[DocumentIngestStatus.DUPLICATE_SKIPPED.value] == 1
    assert second.outcomes[0].source_document_id == first.outcomes[0].source_document_id
    assert FirestoreGraphIntegrityChecker(store).check("all") == ()
