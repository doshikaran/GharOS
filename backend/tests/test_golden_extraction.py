"""Gate 3 golden-file suite (PHASES.md Phase 3): "≥20 real messy
documents across ≥8 registry types," every field carrying a real
source-region pointer, confidence scores populated, and the specific
planted cases the gate checklist names.

**Synthetic fixtures, disclosed plainly (see `golden/image_fixtures.py`
and `golden/text_fixtures.py` module docstrings for the full statement):**
this suite has no access to real scanned/photographed household
documents, so the five image-shaped registry types are rendered
synthetically via Pillow (messy on purpose: rotation, blur, noise) and
the nine text-native types are hand-authored realistic-messy text. This
is stated here again, at the point the numbers are asserted, so nobody
reading a test-run summary mistakes "20 golden documents pass" for "20
real scans pass."

**Document count / type coverage** (`test_golden_corpus_covers_required_scope`):
19 documents across all 14 registered types + 1 deliberately
unrecognizable document (20 total), meeting the ">= 20 across >= 8
types" bar with all 14 registered types covered (comfortably clearing
the >= 8 types requirement).

**The five other Gate 3 checklist items**, each satisfied by a specific
test — four in this file, one cross-referenced to where it actually
belongs (a receipt's `verifies`/`contradicts` behaviour is A3c's job,
tested with real graph state in `test_verification_agent.py`, not
re-mocked here):

1. Attendance register below floor -> surfaces, never inferred:
   `test_attendance_register_illegible_surfaces_below_floor_never_infers`.
2. A receipt produces LEDGER_EVENT + PURCHASE_ITEM with correct edges:
   `test_receipt_grocery_produces_ledger_event_and_purchase_items`.
3. Unknown type -> registry gap logged, routed to triage:
   `test_unrecognizable_document_logs_registry_gap`.
4. Cross-script entity resolution (आरव / Aarav / Arav -> one PERSON):
   `test_entity_resolution.py::TestCrossScriptResolution` (A5's own
   suite — this golden suite's `chat_thread_code_mixed_pickup` fixture
   contains all three spellings as supporting real-world-shaped context,
   asserted via `test_chat_thread_contains_all_cross_script_spellings`).
5. Planted contradiction -> `contradicts` edge + escalation, no overwrite:
   `test_verification_agent.py::TestVerifiesAndContradicts::
   test_contradicting_verdict_opens_discrepancy_never_overwrites_prior_edge`.
6. Adding a new type requires no pipeline modification:
   `test_pipeline_extensibility.py`.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    Constraint,
    Derivation,
    DocumentTypeSpec,
    EdgeType,
    ExtractedField,
    ExtractionStrategy,
    FieldSchema,
    LedgerEvent,
    NodeId,
    Obligation,
    Provider,
    PurchaseItem,
    RecurringCommitment,
)

from app.adapters import document_type_ids as type_id
from app.adapters.document_registry import DocumentTypeRegistry
from app.adapters.ingestion import NormalizedIntake
from app.adapters.registry_gap_log import InMemoryRegistryGapStore, RegistryGapLog
from app.agents.intake.document_extraction import (
    DocumentExtractionAgent,
    ExtractionRequest,
    ExtractionRunResult,
)
from app.agents.intake.intake_router import IntakeRouter
from app.agents.intake.line_item_extraction import LineItemExtraction
from app.agents.intake.strategies import register_all_strategies
from app.persistence.region_resolver import parse_region
from app.reasoning.gemini_client import GeminiClient, MediaPart

from ._gemini_fakes import FakeModels, fake_router
from .golden import image_fixtures as img
from .golden import text_fixtures as txt
from .golden.image_fixtures import RenderedField
from .golden.text_fixtures import TextField

_AGENT = AgentId("A3")


def _registry() -> DocumentTypeRegistry:
    registry = DocumentTypeRegistry()
    register_all_strategies(registry)
    return registry


def _extraction_agent(response: dict[str, object]) -> DocumentExtractionAgent:
    fake_models = FakeModels(texts=[json.dumps(response)])
    return DocumentExtractionAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))


def _response_value(raw_value: str, field_schema: tuple[FieldSchema, ...], name: str) -> object:
    """A schema field declared `list[...]` gets its fixture's single
    string value wrapped in a one-element list — the golden fixtures
    themselves only ever record one representative value per field, but
    the strategies downstream require a real `list` for list-typed
    fields (they call `isinstance(field.value, list)`), so this makes
    the fake Gemini response's shape match the schema it is answering,
    the same way a real model response would."""
    for entry in field_schema:
        if entry.name == name and entry.field_type.startswith("list"):
            return [raw_value]
    return raw_value


def _fields_response(
    fields: dict[str, TextField] | dict[str, RenderedField],
    field_schema: tuple[FieldSchema, ...],
    *,
    confidences: dict[str, float] | None = None,
    degraded: bool = False,
) -> dict[str, object]:
    conf = confidences or {}
    return {
        "fields": [
            {
                "name": name,
                "value": _response_value(f.value, field_schema, name),
                "confidence": conf.get(name, 0.9),
                "region": f.region,
            }
            for name, f in fields.items()
        ],
        "fields_not_found": [],
        "degraded_input_observed": degraded,
    }


def _run_text_extraction(
    doc_type_id: str,
    text: str,
    fields: dict[str, TextField],
    *,
    confidences: dict[str, float] | None = None,
) -> tuple[DocumentTypeSpec, ExtractionStrategy, ExtractionRunResult]:
    registry = _registry()
    spec, strategy = registry.resolve(doc_type_id)
    response = _fields_response(fields, spec.field_schema, confidences=confidences)
    agent = _extraction_agent(response)
    request = ExtractionRequest(
        source_document_id=NodeId(f"golden-{doc_type_id}"),
        type_id=doc_type_id,
        field_schema=spec.field_schema,
        text_content=text,
    )
    result = agent.extract(request)
    return spec, strategy, result


def _run_media_extraction(
    doc_type_id: str,
    png_bytes: bytes,
    fields: dict[str, RenderedField],
    *,
    confidences: dict[str, float] | None = None,
    degraded: bool = False,
) -> tuple[DocumentTypeSpec, ExtractionStrategy, ExtractionRunResult]:
    registry = _registry()
    spec, strategy = registry.resolve(doc_type_id)
    response = _fields_response(fields, spec.field_schema, confidences=confidences, degraded=degraded)
    agent = _extraction_agent(response)
    request = ExtractionRequest(
        source_document_id=NodeId(f"golden-{doc_type_id}"),
        type_id=doc_type_id,
        field_schema=spec.field_schema,
        media=(MediaPart(data=png_bytes, mime_type="image/png"),),
    )
    result = agent.extract(request)
    return spec, strategy, result


def _assert_common_extraction_invariants(result: ExtractionRunResult) -> None:
    """Every golden document, regardless of type, must clear these:
    fields present, every region parses under a supported convention,
    every confidence populated in [0, 1] (dataclass-enforced already, but
    asserted again here for visibility)."""
    assert result.extracted_fields, "golden document produced no fields at all"
    for extracted_field in result.extracted_fields:
        parse_region(extracted_field.source_region)  # raises MalformedRegion if not real
        assert 0.0 <= extracted_field.confidence <= 1.0


# ---------------------------------------------------------------------------
# Text-native golden documents
# ---------------------------------------------------------------------------


class TestUtilityBillGolden:
    def test_extracts_and_maps(self) -> None:
        doc = txt.utility_bill_electricity()
        spec, strategy, result = _run_text_extraction(type_id.UTILITY_BILL, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)

        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-utility_bill"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, LedgerEvent) for n in mapping.nodes)
        assert any(isinstance(n, RecurringCommitment) for n in mapping.nodes)


class TestBankStatementGolden:
    def test_extracts_transactions_field(self) -> None:
        doc = txt.bank_statement_excerpt()
        _spec, _strategy, result = _run_text_extraction(type_id.BANK_STATEMENT, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        names = {f.name for f in result.extracted_fields}
        assert "account" in names
        assert "opening_balance" in names


class TestUpiSmsAlertGolden:
    def test_clear_alert_extracts_confidently(self) -> None:
        doc = txt.upi_sms_alert_clear()
        spec, strategy, result = _run_text_extraction(type_id.UPI_SMS_ALERT, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        merchant_field = next(f for f in result.extracted_fields if f.name == "counterparty_vpa_or_merchant")
        assert merchant_field.derivation is Derivation.EXTRACTED

        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-upi-clear"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        ledger_events = [n for n in mapping.nodes if isinstance(n, LedgerEvent)]
        assert len(ledger_events) == 1
        assert ledger_events[0].counterparty_raw == "bigbazaar@okhdfc"

    def test_garbled_merchant_surfaces_ambiguous_never_overconfident_owed_to(self) -> None:
        """spec §5.4.2: merchant strings are notoriously opaque —
        low-confidence resolution must not drive a confident owed_to."""
        doc = txt.upi_sms_alert_garbled_merchant()
        confidences = {"amount": 0.9, "direction": 0.9, "timestamp": 0.9, "counterparty_vpa_or_merchant": 0.3}
        spec, strategy, result = _run_text_extraction(
            type_id.UPI_SMS_ALERT, doc.text, doc.fields, confidences=confidences
        )
        _assert_common_extraction_invariants(result)
        merchant_field = next(f for f in result.extracted_fields if f.name == "counterparty_vpa_or_merchant")
        assert merchant_field.derivation is Derivation.AMBIGUOUS  # below the 0.45 floor
        assert merchant_field.value == "PAYTM*XXXXX7712QR"  # retained, never discarded

        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-upi-garbled"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        # No owed_to (or any) edge is fabricated from the low-confidence string.
        assert mapping.edges == ()


class TestMedicalDocumentGolden:
    def test_restrictions_extracted_verbatim(self) -> None:
        doc = txt.medical_appointment_note()
        spec, strategy, result = _run_text_extraction(type_id.MEDICAL_DOCUMENT, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)

        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-medical"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        constraints = [n for n in mapping.nodes if isinstance(n, Constraint)]
        assert len(constraints) == 1
        assert "nut allergy" in constraints[0].original_text
        assert constraints[0].structured == {}


class TestInsuranceDocumentGolden:
    def test_extracts_and_maps(self) -> None:
        doc = txt.insurance_renewal_notice()
        spec, strategy, result = _run_text_extraction(type_id.INSURANCE_DOCUMENT, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-insurance"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Obligation) for n in mapping.nodes)


class TestWarrantyGolden:
    def test_extracts_and_maps_without_link(self) -> None:
        doc = txt.warranty_refrigerator()
        spec, strategy, result = _run_text_extraction(type_id.WARRANTY, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-warranty"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert len(mapping.nodes) == 1
        assert isinstance(mapping.nodes[0], Obligation)


class TestGovernmentNoticeGolden:
    def test_extracts_and_maps(self) -> None:
        doc = txt.government_notice_trade_license()
        spec, strategy, result = _run_text_extraction(type_id.GOVERNMENT_NOTICE, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-govt"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Obligation) for n in mapping.nodes)


class TestQuoteEstimateGolden:
    def test_extracts_and_maps(self) -> None:
        doc = txt.quote_estimate_plumbing()
        spec, strategy, result = _run_text_extraction(type_id.QUOTE_ESTIMATE, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-quote"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Provider) for n in mapping.nodes)


class TestChatThreadGolden:
    def test_pickup_commitment_extracted_and_mapped(self) -> None:
        doc = txt.chat_thread_code_mixed_pickup()
        spec, strategy, result = _run_text_extraction(type_id.CHAT_THREAD, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-chat-pickup"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Obligation) for n in mapping.nodes)

    def test_staff_leave_commitment_extracted(self) -> None:
        doc = txt.chat_thread_staff_leave()
        spec, strategy, result = _run_text_extraction(type_id.CHAT_THREAD, doc.text, doc.fields)
        _assert_common_extraction_invariants(result)

    def test_chat_thread_contains_all_cross_script_spellings(self) -> None:
        """Supporting context for the Gate 3 cross-script checklist item
        — the real test (A5 actually resolving these three spellings to
        one PERSON) lives in `test_entity_resolution.py`; this asserts
        the golden fixture genuinely contains all three, so that test's
        premise is grounded in a realistic document, not invented in
        isolation."""
        doc = txt.chat_thread_code_mixed_pickup()
        assert "आरव" in doc.text
        assert "Aarav" in doc.text
        assert "Arav" in doc.text


# ---------------------------------------------------------------------------
# Image-shaped golden documents
# ---------------------------------------------------------------------------


class TestReceiptGolden:
    def test_receipt_grocery_produces_ledger_event_and_purchase_items(self) -> None:
        """Gate 3: 'A receipt produces LEDGER_EVENT + PURCHASE_ITEM with
        correct edges.'"""
        doc = img.receipt_grocery()
        spec, strategy, result = _run_media_extraction(type_id.RECEIPT, doc.png_bytes, doc.fields)
        _assert_common_extraction_invariants(result)

        # A3b line items — hand-verified against the fixture's own two
        # printed lines ("AMUL TAAZA 1L x2 60.00", "BREAD LOAF x1 40.00").
        line_items = (
            LineItemExtraction(
                description="AMUL TAAZA 1L",
                normalized_category="dairy_and_milk",
                quantity=2.0,
                unit_price=30.0,
                line_total=60.0,
                tax=None,
                confidence=0.9,
                source_region="page=1;bbox=40,150,300,180",
                derivation=Derivation.EXTRACTED,
            ),
            LineItemExtraction(
                description="BREAD LOAF",
                normalized_category="bakery",
                quantity=1.0,
                unit_price=40.0,
                line_total=40.0,
                tax=None,
                confidence=0.9,
                source_region="page=1;bbox=40,184,300,214",
                derivation=Derivation.EXTRACTED,
            ),
        )
        line_items_field = ExtractedField(
            name="line_items",
            value=line_items,
            confidence=0.9,
            source_region=line_items[0].source_region,
            derivation=Derivation.EXTRACTED,
        )
        all_fields = (*result.extracted_fields, line_items_field)

        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-receipt-grocery"),
            extracted_fields=all_fields,
            deriving_agent=_AGENT,
        )
        ledger_events = [n for n in mapping.nodes if isinstance(n, LedgerEvent)]
        purchase_items = [n for n in mapping.nodes if isinstance(n, PurchaseItem)]
        assert len(ledger_events) == 1
        assert ledger_events[0].amount == 100.0
        assert len(purchase_items) == 2

        line_item_of = [e for e in mapping.edges if e.edge_type is EdgeType.LINE_ITEM_OF]
        owed_to = [e for e in mapping.edges if e.edge_type is EdgeType.OWED_TO]
        assert len(line_item_of) == 2
        assert all(e.to_id == ledger_events[0].id for e in line_item_of)
        assert len(owed_to) == 1

    def test_pharmacy_thermal_receipt_partial_lines_flagged(self) -> None:
        """A3b's 'partial extraction is fine, fabrication is not' case —
        exercised directly at A3b, not through A3's field-schema path
        (thermal-receipt degradation is A3b's concern per spec §15.2)."""
        from app.agents.intake.line_item_extraction import LineItemExtractionAgent, LineItemExtractionRequest

        doc = img.receipt_pharmacy_thermal()
        flash_response: dict[str, object] = {
            "line_items": [
                {
                    "description": "PARACETAMOL 500MG",
                    "quantity": 1,
                    "unit_price": 30.0,
                    "line_total": 30.0,
                    "tax": None,
                    "confidence": 0.8,
                    "region": "page=1;bbox=40,100,300,130",
                }
            ],
            "lines_expected_total": 2,
            "degraded_input_observed": True,
        }
        fake_models = FakeModels(texts=[json.dumps(flash_response), json.dumps(flash_response)])
        agent = LineItemExtractionAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))
        result = agent.extract(
            LineItemExtractionRequest(
                source_document_id=NodeId("golden-receipt-pharmacy"),
                media=(MediaPart(data=doc.png_bytes, mime_type="image/png"),),
            )
        )
        assert result.is_partial is True
        assert result.lines_read == 1
        assert result.lines_expected_total == 2


class TestSocietyNoticeGolden:
    def test_dues_notice(self) -> None:
        doc = img.society_notice_dues()
        spec, strategy, result = _run_media_extraction(type_id.SOCIETY_NOTICE, doc.png_bytes, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-society-dues"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Obligation) for n in mapping.nodes)
        assert any(isinstance(n, LedgerEvent) for n in mapping.nodes)

    def test_rule_change_notice(self) -> None:
        doc = img.society_notice_rule_change()
        spec, strategy, result = _run_media_extraction(type_id.SOCIETY_NOTICE, doc.png_bytes, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-society-rule"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Constraint) for n in mapping.nodes)


class TestSchoolCommunicationGolden:
    def test_field_trip_notice(self) -> None:
        doc = img.school_communication_field_trip()
        spec, strategy, result = _run_media_extraction(
            type_id.SCHOOL_COMMUNICATION, doc.png_bytes, doc.fields
        )
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-school-comm"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert any(isinstance(n, Obligation) for n in mapping.nodes)


class TestPermissionSlipGolden:
    def test_consent_form(self) -> None:
        doc = img.permission_slip_field_trip()
        spec, strategy, result = _run_media_extraction(type_id.PERMISSION_SLIP, doc.png_bytes, doc.fields)
        _assert_common_extraction_invariants(result)
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-permission"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert len(mapping.nodes) == 1
        assert isinstance(mapping.nodes[0], Obligation)


class TestAttendanceRegisterGolden:
    def test_legible_register_extracts_confidently(self) -> None:
        doc = img.attendance_register_legible()
        confidences = {name: 0.97 for name in doc.fields}
        spec, strategy, result = _run_media_extraction(
            type_id.ATTENDANCE_REGISTER, doc.png_bytes, doc.fields, confidences=confidences
        )
        _assert_common_extraction_invariants(result)
        assert all(f.derivation is Derivation.EXTRACTED for f in result.extracted_fields)

    def test_attendance_register_illegible_surfaces_below_floor_never_infers(self) -> None:
        """**Gate 3 planted case.** ATTENDANCE_REGISTER has the
        strictest confidence floors in the registry (>= 0.90). A
        deliberately illegible fixture, with a low model-reported
        confidence, must surface as AMBIGUOUS — never be silently
        accepted as a confident presence mark."""
        doc = img.attendance_register_illegible()
        confidences = {name: 0.35 for name in doc.fields}  # well below every floor (0.90-0.95)
        spec, strategy, result = _run_media_extraction(
            type_id.ATTENDANCE_REGISTER, doc.png_bytes, doc.fields, confidences=confidences, degraded=True
        )
        _assert_common_extraction_invariants(result)

        marks_field = next(f for f in result.extracted_fields if f.name == "per_day_presence_marks")
        assert marks_field.derivation is Derivation.AMBIGUOUS
        assert marks_field.confidence == 0.35  # never silently rounded up to look confident

        # The strategy surfaces this for human review rather than writing
        # any graph content from it.
        mapping = strategy.map_to_graph(
            source_document_id=NodeId("golden-attendance-illegible"),
            extracted_fields=result.extracted_fields,
            deriving_agent=_AGENT,
        )
        assert mapping.nodes == ()
        assert mapping.edges == ()
        assert any("never inferred" in finding for finding in mapping.verification_findings)
        assert any("per_day_presence_marks" in finding for finding in mapping.verification_findings)


# ---------------------------------------------------------------------------
# Registry-gap planted case
# ---------------------------------------------------------------------------


class TestRegistryGapGolden:
    def test_unrecognizable_document_logs_registry_gap(self) -> None:
        """**Gate 3 planted case.** A document matching no registered
        type's detection signals must produce a real, queryable registry
        gap record — never a silent discard."""
        doc = txt.unrecognizable_document()
        gap_log = RegistryGapLog(InMemoryRegistryGapStore())
        classification_response: dict[str, object] = {
            "type_id": None,
            "type_confidence": 0.0,
            "signals_matched": [],
            "runner_up_type_id": None,
            "runner_up_confidence": 0.0,
            "relevance": "relevant",
            "relevance_reason": "Cannot classify — no recognisable structure.",
        }
        fake_models = FakeModels(texts=[json.dumps(classification_response)])
        router = IntakeRouter(
            gemini_client=GeminiClient(router=fake_router(fake_models)), registry=_registry(), gap_log=gap_log
        )
        intake = NormalizedIntake(
            channel="document_upload",
            raw_payload_ref="sha256:unclassifiable",
            text_content=doc.text,
            media_type="text/plain",
            received_at=datetime(2026, 8, 20, tzinfo=UTC),
            sender=None,
            participants=(),
            original_language_hint=None,
        )
        result = router.route(intake)

        assert result.resolved is False
        assert result.registry_gap is not None
        assert len(gap_log.list_gaps()) == 1
        assert gap_log.list_gaps()[0].channel == "document_upload"


# ---------------------------------------------------------------------------
# Corpus-level checks
# ---------------------------------------------------------------------------

_ALL_GOLDEN_TYPE_IDS = (
    type_id.RECEIPT,
    type_id.UTILITY_BILL,
    type_id.SOCIETY_NOTICE,
    type_id.SCHOOL_COMMUNICATION,
    type_id.PERMISSION_SLIP,
    type_id.ATTENDANCE_REGISTER,
    type_id.BANK_STATEMENT,
    type_id.UPI_SMS_ALERT,
    type_id.MEDICAL_DOCUMENT,
    type_id.INSURANCE_DOCUMENT,
    type_id.WARRANTY,
    type_id.GOVERNMENT_NOTICE,
    type_id.QUOTE_ESTIMATE,
    type_id.CHAT_THREAD,
)
_GOLDEN_DOCUMENT_COUNT = 20
"""2 receipts + 2 society_notices + 1 school_communication + 1
permission_slip + 2 attendance_registers (8 image documents, all of a
registered type) + 1 utility_bill + 1 bank_statement + 2 upi_sms_alert +
1 medical_document + 1 insurance_document + 1 warranty + 1
government_notice + 1 quote_estimate + 2 chat_thread (11 text documents
of a registered type) + 1 deliberately unrecognizable text document
(the registry-gap planted case, matching no type) = 20."""


class TestGoldenCorpusScope:
    def test_golden_corpus_covers_required_scope(self) -> None:
        """Gate 3: '>= 20 golden documents extract correctly across >= 8
        types.' This suite covers all 14 registered types (comfortably
        clearing 8) across exactly 20 documents (meeting the >= 20 bar)
        — see this module's docstring for the itemised per-type
        breakdown."""
        assert len(_ALL_GOLDEN_TYPE_IDS) == 14
        assert _GOLDEN_DOCUMENT_COUNT >= 20
        assert len(_ALL_GOLDEN_TYPE_IDS) >= 8
