"""Unit tests for the fourteen `ExtractionStrategy` implementations
(`app.agents.intake.strategies`) — each constructed with hand-built
`ExtractedField` tuples (ADR-008: "independently unit-testable... without
needing a real document, a real LLM call, or a real registry lookup").

Also proves: `test_registration.py`-style coverage that all fourteen
register cleanly (`test_all_fourteen_register_without_error`), and the
`MappingInputIncomplete` "never fabricate a missing required field" rule
(`TestMappingInputIncomplete`).
"""

from __future__ import annotations

import pytest
from contracts.graph_types import (
    AgentId,
    AttendanceRecord,
    Constraint,
    Derivation,
    EdgeType,
    ExtractedField,
    LedgerEvent,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Provider,
    PurchaseItem,
    RecurringCommitment,
)

from app.adapters import document_type_ids as type_id
from app.adapters.document_registry import DocumentTypeRegistry
from app.agents.intake.line_item_extraction import LineItemExtraction
from app.agents.intake.strategies import register_all_strategies
from app.agents.intake.strategies.attendance_register_strategy import AttendanceRegisterExtractionStrategy
from app.agents.intake.strategies.bank_statement_strategy import BankStatementExtractionStrategy
from app.agents.intake.strategies.chat_thread_strategy import ChatThreadExtractionStrategy
from app.agents.intake.strategies.errors import MappingInputIncomplete
from app.agents.intake.strategies.government_notice_strategy import GovernmentNoticeExtractionStrategy
from app.agents.intake.strategies.insurance_document_strategy import InsuranceDocumentExtractionStrategy
from app.agents.intake.strategies.medical_document_strategy import MedicalDocumentExtractionStrategy
from app.agents.intake.strategies.permission_slip_strategy import PermissionSlipExtractionStrategy
from app.agents.intake.strategies.quote_estimate_strategy import QuoteEstimateExtractionStrategy
from app.agents.intake.strategies.receipt_strategy import ReceiptExtractionStrategy
from app.agents.intake.strategies.school_communication_strategy import SchoolCommunicationExtractionStrategy
from app.agents.intake.strategies.society_notice_strategy import SocietyNoticeExtractionStrategy
from app.agents.intake.strategies.upi_sms_alert_strategy import UpiSmsAlertExtractionStrategy
from app.agents.intake.strategies.utility_bill_strategy import UtilityBillExtractionStrategy
from app.agents.intake.strategies.warranty_strategy import WarrantyExtractionStrategy

_SRC = NodeId("doc-1")
_AGENT = AgentId("A3")


def _f(name: str, value: object, *, region: str = "0-10", confidence: float = 0.9) -> ExtractedField:
    return ExtractedField(
        name=name, value=value, confidence=confidence, source_region=region, derivation=Derivation.EXTRACTED
    )


class TestRegistryWiring:
    def test_all_fourteen_register_without_error(self) -> None:
        registry = DocumentTypeRegistry()
        register_all_strategies(registry)
        assert len(registry) == 14
        for tid in type_id.ALL_TYPE_IDS:
            spec, strategy = registry.resolve(tid)
            assert spec.type_id == tid
            assert strategy is not None


class TestReceiptStrategy:
    def test_produces_ledger_event_and_purchase_items_with_correct_edges(self) -> None:
        """Gate 3: 'A receipt produces LEDGER_EVENT + PURCHASE_ITEM with
        correct edges.'"""
        line_items = (
            LineItemExtraction(
                description="AMUL TAAZA 1L",
                normalized_category="dairy_and_milk",
                quantity=2.0,
                unit_price=30.0,
                line_total=60.0,
                tax=None,
                confidence=0.9,
                source_region="10-25",
                derivation=Derivation.EXTRACTED,
            ),
        )
        fields = (
            _f("merchant_name", "Big Bazaar"),
            _f("total", 60.0),
            _f("transaction_datetime", "2026-08-15T10:00:00"),
            _f("line_items", line_items),
        )
        result = ReceiptExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )

        ledger_events = [n for n in result.nodes if isinstance(n, LedgerEvent)]
        purchase_items = [n for n in result.nodes if isinstance(n, PurchaseItem)]
        assert len(ledger_events) == 1
        assert len(purchase_items) == 1
        assert purchase_items[0].ledger_event_id == ledger_events[0].id
        assert purchase_items[0].normalized_category == "dairy_and_milk"

        line_item_of_edges = [e for e in result.edges if e.edge_type is EdgeType.LINE_ITEM_OF]
        owed_to_edges = [e for e in result.edges if e.edge_type is EdgeType.OWED_TO]
        assert len(line_item_of_edges) == 1
        assert line_item_of_edges[0].from_id == purchase_items[0].id
        assert line_item_of_edges[0].to_id == ledger_events[0].id
        assert len(owed_to_edges) == 1
        assert owed_to_edges[0].from_id == ledger_events[0].id

    def test_missing_required_field_raises_never_fabricates(self) -> None:
        fields = (_f("merchant_name", "Big Bazaar"),)  # no total, no datetime
        with pytest.raises(MappingInputIncomplete):
            ReceiptExtractionStrategy().map_to_graph(
                source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
            )


class TestUtilityBillStrategy:
    def test_produces_ledger_event_and_recurring_commitment_no_obligation(self) -> None:
        fields = (
            _f("provider", "City Power Co"),
            _f("amount_due", 1200.0),
            _f("due_date", "2026-09-05"),
            _f("billing_period_start", "2026-08-01"),
            _f("billing_period_end", "2026-08-30"),
        )
        result = UtilityBillExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert any(isinstance(n, LedgerEvent) for n in result.nodes)
        commitments = [n for n in result.nodes if isinstance(n, RecurringCommitment)]
        assert len(commitments) == 1
        assert commitments[0].cadence == "monthly"
        # Documented registry inconsistency: no OBLIGATION/STATES this phase.
        assert not any(isinstance(n, Obligation) for n in result.nodes)


class TestSocietyNoticeStrategy:
    def test_dues_notice_produces_obligation_and_ledger_event(self) -> None:
        fields = (
            _f("society_name", "Green Meadows CHS"),
            _f("notice_type", "dues"),
            _f("amount", 3500.0),
            _f("due_date", "2026-09-10"),
        )
        result = SocietyNoticeExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert any(isinstance(n, Obligation) for n in result.nodes)
        assert any(isinstance(n, LedgerEvent) for n in result.nodes)
        assert any(e.edge_type is EdgeType.STATES for e in result.edges)

    def test_rule_change_notice_produces_constraint(self) -> None:
        fields = (
            _f("society_name", "Green Meadows CHS"),
            _f("notice_type", "rule_change: parking hours"),
        )
        result = SocietyNoticeExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert any(isinstance(n, Constraint) for n in result.nodes)


class TestSchoolCommunicationStrategy:
    def test_produces_one_obligation_per_requirement_plus_primary(self) -> None:
        fields = (
            _f("institution", "Green Valley School"),
            _f("student", "Aarav"),
            _f("communication_type", "field_trip"),
            _f("response_deadline", "2026-09-01"),
            _f("requirements", ["signed permission slip", "nut-free lunch"]),
        )
        result = SchoolCommunicationExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        obligations = [n for n in result.nodes if isinstance(n, Obligation)]
        assert len(obligations) == 3  # primary + 2 requirements
        states_edges = [e for e in result.edges if e.edge_type is EdgeType.STATES]
        assert len(states_edges) == 3


class TestPermissionSlipStrategy:
    def test_produces_obligation_with_states_edge(self) -> None:
        fields = (
            _f("issuing_body", "Green Valley School"),
            _f("subject_person", "Aarav"),
            _f("consent_description", "Field trip to the science museum"),
            _f("return_deadline", "2026-08-27"),
        )
        result = PermissionSlipExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert len(result.nodes) == 1
        assert isinstance(result.nodes[0], Obligation)
        assert result.edges[0].edge_type is EdgeType.STATES


_ATTENDANCE_MARKS = [
    {"day": "01", "mark": "present"},
    {"day": "02", "mark": "present"},
    {"day": "03", "mark": "absent"},
    {"day": "04", "mark": "leave"},
    {"day": "05", "mark": "present"},
]


class TestAttendanceRegisterStrategy:
    def test_clean_register_writes_attendance_record_and_salary_obligation(self) -> None:
        """ADR-013 / DEBT-004: a confidently-extracted register now
        produces a real `AttendanceRecord` (rollup + per-day marks) plus
        the salary `Obligation` it feeds and the `implies` edge anchoring
        that obligation to the SOURCE_DOCUMENT."""
        fields = (
            _f("staff_member", "Radha"),
            _f("month", "2026-08"),
            _f("per_day_presence_marks", _ATTENDANCE_MARKS),
            _f("advance_notations_margin", ["hasil 2000 - 10 tarikh"]),
        )
        result = AttendanceRegisterExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        records = [n for n in result.nodes if isinstance(n, AttendanceRecord)]
        obligations = [n for n in result.nodes if isinstance(n, Obligation)]
        assert len(records) == 1
        record = records[0]
        assert record.month == "2026-08"
        assert record.days_present == 3
        assert record.days_absent == 1
        assert record.days_on_leave == 1
        assert record.total_days_in_period == 5
        assert record.daily_marks["04"] == "leave"
        assert record.advance_notations == ("hasil 2000 - 10 tarikh",)
        assert record.provenance.source_ref is not None
        assert str(record.provenance.source_ref.source_document_id) == str(_SRC)
        assert len(obligations) == 1
        assert obligations[0].obligation_type == "payment"
        assert obligations[0].stated_or_implied is ObligationDerivation.IMPLIED
        assert obligations[0].status is ObligationStatus.DERIVED
        implies = [e for e in result.edges if e.edge_type is EdgeType.IMPLIES]
        assert [e.from_id for e in implies] == [_SRC]
        assert [e.to_id for e in implies] == [obligations[0].id]

    def test_unresolved_staff_leaves_attendance_of_for_a_downstream_pass(self) -> None:
        """ADR-008: `map_to_graph` has no `GraphReader`. With no injected
        `staff_index`, the strategy does not fabricate an owner — it emits
        the `AttendanceRecord` with an explicit unresolved sentinel, no
        `attendance_of` edge, and a `verification_findings` note."""
        fields = (
            _f("staff_member", "Radha"),
            _f("month", "2026-08"),
            _f("per_day_presence_marks", _ATTENDANCE_MARKS),
        )
        result = AttendanceRegisterExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        record = next(n for n in result.nodes if isinstance(n, AttendanceRecord))
        assert str(record.staff_person_id) == "person:unresolved"
        assert not any(e.edge_type is EdgeType.ATTENDANCE_OF for e in result.edges)
        assert any("downstream entity-resolution pass" in finding for finding in result.verification_findings)

    def test_injected_staff_index_writes_the_attendance_of_edge(self) -> None:
        person_id = NodeId("person-radha")
        fields = (
            _f("staff_member", "Radha"),
            _f("month", "2026-08"),
            _f("per_day_presence_marks", _ATTENDANCE_MARKS),
        )
        result = AttendanceRegisterExtractionStrategy(staff_index={"Radha": person_id}).map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        record = next(n for n in result.nodes if isinstance(n, AttendanceRecord))
        assert record.staff_person_id == person_id
        attendance_of = [e for e in result.edges if e.edge_type is EdgeType.ATTENDANCE_OF]
        assert [e.from_id for e in attendance_of] == [record.id]
        assert [e.to_id for e in attendance_of] == [person_id]

    def test_missing_required_field_raises_mapping_input_incomplete(self) -> None:
        """`per_day_presence_marks` is required (spec §5.4.2). Its absence
        routes the document to human triage, never a fabricated record."""
        fields = (
            _f("staff_member", "Radha"),
            _f("month", "2026-08"),
        )
        with pytest.raises(MappingInputIncomplete) as excinfo:
            AttendanceRegisterExtractionStrategy().map_to_graph(
                source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
            )
        assert "per_day_presence_marks" in excinfo.value.missing_fields

    def test_ambiguous_marks_write_no_graph_content_and_surface_for_review(self) -> None:
        """Gate 3 (spec §5.4.2): below-floor attendance marks must surface,
        never be silently accepted — and an uncertain register must not
        become an `AttendanceRecord` that feeds a wrong salary."""
        fields = (
            _f("staff_member", "Radha"),
            _f("month", "August 2026"),
            ExtractedField(
                name="per_day_presence_marks",
                value=[{"day": 14, "mark": "unclear"}],
                confidence=0.5,  # well below the 0.90+ attendance floor
                source_region="page=1;bbox=0,0,50,50",
                derivation=Derivation.AMBIGUOUS,
            ),
        )
        result = AttendanceRegisterExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert result.nodes == ()
        assert result.edges == ()
        assert any("per_day_presence_marks" in finding for finding in result.verification_findings)
        assert any("never inferred" in finding for finding in result.verification_findings)


class TestBankStatementStrategy:
    def test_produces_one_ledger_event_per_transaction(self) -> None:
        fields = (
            _f(
                "transactions",
                [
                    {
                        "date": "2026-08-01",
                        "description": "ATM withdrawal",
                        "amount": 2000.0,
                        "direction": "debit",
                    },
                    {
                        "date": "2026-08-03",
                        "description": "Salary credit",
                        "amount": 50000.0,
                        "direction": "credit",
                    },
                ],
            ),
        )
        result = BankStatementExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        ledger_events = [n for n in result.nodes if isinstance(n, LedgerEvent)]
        assert len(ledger_events) == 2


class TestUpiSmsAlertStrategy:
    def test_low_confidence_merchant_produces_no_owed_to_edge(self) -> None:
        """spec: low-confidence merchant resolution must not drive an
        overconfident owed_to edge."""
        fields = (
            _f("amount", 499.0),
            _f("direction", "debit"),
            _f("counterparty_vpa_or_merchant", "PAYTM*XXXXX", confidence=0.3),
            _f("timestamp", "2026-08-20T14:00:00"),
        )
        result = UpiSmsAlertExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert result.edges == ()
        ledger_events = [n for n in result.nodes if isinstance(n, LedgerEvent)]
        assert ledger_events[0].counterparty_raw == "PAYTM*XXXXX"


class TestMedicalDocumentStrategy:
    def test_restrictions_recorded_verbatim_never_interpreted(self) -> None:
        fields = (
            _f("patient", "Aarav"),
            _f("provider", "Dr. Mehta"),
            _f("stated_restrictions", ["Nut allergy — avoid all nuts", "Avoid dairy after 6pm"]),
        )
        result = MedicalDocumentExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        constraints = [n for n in result.nodes if isinstance(n, Constraint)]
        assert len(constraints) == 2
        assert {c.original_text for c in constraints} == {
            "Nut allergy — avoid all nuts",
            "Avoid dairy after 6pm",
        }
        assert all(c.structured == {} for c in constraints)  # no invented interpretation
        nut_constraint = next(c for c in constraints if "allergy" in c.original_text)
        assert nut_constraint.severity.value == "hard"

    def test_appointment_dates_produce_obligations(self) -> None:
        fields = (
            _f("patient", "Aarav"),
            _f("provider", "Dr. Mehta"),
            _f("appointment_or_followup_dates", ["2026-09-15"]),
        )
        result = MedicalDocumentExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert any(isinstance(n, Obligation) for n in result.nodes)


class TestInsuranceDocumentStrategy:
    def test_produces_commitment_obligation_and_constraint(self) -> None:
        fields = (
            _f("insurer", "Star Health"),
            _f("premium", 15000.0),
            _f("coverage_type", "family_floater"),
            _f("renewal_date", "2027-01-01"),
            _f("premium_due_date", "2026-12-01"),
            _f("coverage_limits", 500000.0),
        )
        result = InsuranceDocumentExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert any(isinstance(n, RecurringCommitment) for n in result.nodes)
        assert any(isinstance(n, Obligation) for n in result.nodes)
        assert any(isinstance(n, Constraint) for n in result.nodes)


class TestWarrantyStrategy:
    def test_covers_edge_links_back_to_originating_purchase_item(self) -> None:
        fields = (
            _f("product", "Samsung Refrigerator"),
            _f("warranty_expiry", "2028-06-01"),
            _f("originating_purchase_item_id", "purchase_item:abc123", confidence=1.0),
        )
        result = WarrantyExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        covers_edges = [e for e in result.edges if e.edge_type is EdgeType.COVERS]
        assert len(covers_edges) == 1
        assert covers_edges[0].to_id == NodeId("purchase_item:abc123")
        warranty_obligation = result.nodes[0]
        assert isinstance(warranty_obligation, Obligation)
        assert covers_edges[0].from_id == warranty_obligation.id

    def test_no_link_supplied_produces_no_covers_edge_and_flags_finding(self) -> None:
        fields = (
            _f("product", "Samsung Refrigerator"),
            _f("warranty_expiry", "2028-06-01"),
        )
        result = WarrantyExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert not any(e.edge_type is EdgeType.COVERS for e in result.edges)
        assert result.verification_findings != ()


class TestGovernmentNoticeStrategy:
    def test_produces_high_consequence_obligation(self) -> None:
        fields = (
            _f("issuing_body", "Municipal Corporation"),
            _f("required_action", "Renew trade license"),
            _f("deadline", "2026-10-01"),
        )
        result = GovernmentNoticeExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert len(result.nodes) == 1
        assert isinstance(result.nodes[0], Obligation)


class TestQuoteEstimateStrategy:
    def test_produces_provider_node(self) -> None:
        fields = (
            _f("provider", "ABC Plumbing"),
            _f("scope_of_work", "Fix kitchen sink leak"),
            _f("line_item_costs", [{"amount": 1500.0}, {"amount": 500.0}]),
        )
        result = QuoteEstimateExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        providers = [n for n in result.nodes if isinstance(n, Provider)]
        assert len(providers) == 1
        assert providers[0].name == "ABC Plumbing"
        assert result.edges == ()


class TestChatThreadStrategy:
    def test_produces_one_obligation_per_commitment(self) -> None:
        fields = (
            _f("participants", ["Dad", "Mom"]),
            _f("timestamps", ["2026-08-20T09:00:00"]),
            _f("message_content", ["I'll pick her up Friday"]),
            _f("embedded_commitments", ["I'll pick her up Friday"]),
        )
        result = ChatThreadExtractionStrategy().map_to_graph(
            source_document_id=_SRC, extracted_fields=fields, deriving_agent=_AGENT
        )
        assert len(result.nodes) == 1
        obligation = result.nodes[0]
        assert isinstance(obligation, Obligation)
        assert obligation.title == "I'll pick her up Friday"
        assert obligation.due_at is None  # never inferred from context


class TestMappingInputIncomplete:
    def test_carries_type_id_and_missing_field_names(self) -> None:
        with pytest.raises(MappingInputIncomplete) as exc_info:
            ReceiptExtractionStrategy().map_to_graph(
                source_document_id=_SRC, extracted_fields=(), deriving_agent=_AGENT
            )
        assert exc_info.value.type_id == "receipt"
        assert "merchant_name" in exc_info.value.missing_fields
