"""Cross-checks every one of the fourteen `DocumentTypeSpec` entries
against `GharOS_Build_Spec_v2.md` §5.4.2's actual per-type field lists —
not just "some fields exist," but the exact field-name set each type's
spec prose names (transcribed independently in each test function's
comment, so a regression in `document_type_specs.py` that quietly drops
or renames a field is caught even though both this test and that module
were written by the same phase's work).

Also proves the one binding numeric constraint spec §5.4.2 states
explicitly: ATTENDANCE_REGISTER's confidence floors are the strictest in
the registry.
"""

from __future__ import annotations

from contracts.graph_types import DocumentTypeSpec, EdgeType

from app.adapters import document_type_ids as type_id
from app.adapters.document_type_specs import (
    _ATTENDANCE_MIN_FLOOR,
    ALL_DOCUMENT_TYPE_SPECS,
    DOCUMENT_TYPE_SPECS_BY_ID,
)


def _field_names(spec: DocumentTypeSpec) -> frozenset[str]:
    return frozenset(f.name for f in spec.field_schema)


# ---------------------------------------------------------------------------
# Registry-wide shape
# ---------------------------------------------------------------------------


def test_all_fourteen_canonical_type_ids_are_registered_as_specs() -> None:
    assert len(type_id.ALL_TYPE_IDS) == 14
    assert len(set(type_id.ALL_TYPE_IDS)) == 14, "type_id list must have no duplicates"
    assert {spec.type_id for spec in ALL_DOCUMENT_TYPE_SPECS} == set(type_id.ALL_TYPE_IDS)
    assert len(ALL_DOCUMENT_TYPE_SPECS) == 14


def test_every_spec_has_nonempty_detection_signals_and_field_schema() -> None:
    for spec in ALL_DOCUMENT_TYPE_SPECS:
        assert spec.detection_signals, f"{spec.type_id} has no detection signals"
        assert spec.field_schema, f"{spec.type_id} has no field schema"
        assert spec.target_node_types, f"{spec.type_id} has no target node types"
        assert spec.downstream_subsystems, f"{spec.type_id} has no downstream subsystems"


def test_every_field_confidence_floor_is_a_valid_probability() -> None:
    for spec in ALL_DOCUMENT_TYPE_SPECS:
        for f in spec.field_schema:
            assert 0.0 <= f.confidence_floor <= 1.0, f"{spec.type_id}.{f.name} floor out of range"


def test_attendance_register_floors_are_the_strictest_in_the_registry() -> None:
    """Spec §5.4.2: 'Confidence floors: strictest in the registry —
    handwriting misread directly causes wrong salary payment.' Every
    ATTENDANCE_REGISTER field floor must be >= every other type's every
    field floor."""
    attendance_spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.ATTENDANCE_REGISTER]
    attendance_floors = [f.confidence_floor for f in attendance_spec.field_schema]
    assert attendance_floors, "attendance register must have fields"
    assert min(attendance_floors) >= _ATTENDANCE_MIN_FLOOR

    other_floors = [
        f.confidence_floor
        for spec in ALL_DOCUMENT_TYPE_SPECS
        if spec.type_id != type_id.ATTENDANCE_REGISTER
        for f in spec.field_schema
    ]
    assert other_floors, "sanity: other types must have fields to compare against"
    assert max(other_floors) < min(attendance_floors), (
        "every non-attendance field floor must be strictly below every attendance field floor"
    )


def test_target_edge_types_are_all_real_frozen_edge_type_members() -> None:
    for spec in ALL_DOCUMENT_TYPE_SPECS:
        for edge_type in spec.target_edge_types:
            assert isinstance(edge_type, EdgeType)


# ---------------------------------------------------------------------------
# Per-type field-name cross-checks against spec §5.4.2 prose
# ---------------------------------------------------------------------------


def test_receipt_fields_match_spec() -> None:
    # §5.4.2: "merchant name and category · transaction datetime · payment
    # method and last-4 · line items (description, quantity, unit price,
    # line total, tax) · subtotal, tax, discounts, total · loyalty/account
    # identifiers"
    expected = {
        "merchant_name",
        "merchant_category",
        "transaction_datetime",
        "payment_method",
        "payment_last4",
        "line_items",
        "subtotal",
        "tax",
        "discounts",
        "total",
        "loyalty_account_id",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.RECEIPT]
    assert _field_names(spec) == expected
    assert spec.target_node_types == ("LEDGER_EVENT", "PURCHASE_ITEM")
    assert EdgeType.LINE_ITEM_OF in spec.target_edge_types
    assert EdgeType.EVIDENCES_EFFORT in spec.target_edge_types


def test_utility_bill_fields_match_spec() -> None:
    # §5.4.2: "provider · account identifier · billing period · consumption
    # reading and units · amount due · due date · late-fee terms · prior
    # balance"
    expected = {
        "provider",
        "account_identifier",
        "billing_period_start",
        "billing_period_end",
        "consumption_reading",
        "consumption_units",
        "amount_due",
        "due_date",
        "late_fee_terms",
        "prior_balance",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.UTILITY_BILL]
    assert _field_names(spec) == expected
    assert spec.target_node_types == ("LEDGER_EVENT", "RECURRING_COMMITMENT")


def test_society_notice_fields_match_spec() -> None:
    # §5.4.2: "society name · unit · notice type (...) · amount if any ·
    # due date · effective date for rule changes · contact"
    expected = {"society_name", "unit", "notice_type", "amount", "due_date", "effective_date", "contact"}
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.SOCIETY_NOTICE]
    assert _field_names(spec) == expected


def test_school_communication_fields_match_spec() -> None:
    # §5.4.2: "institution · student · communication type (...) · dates ·
    # amounts · requirements (...) · response deadline"
    expected = {
        "institution",
        "student",
        "communication_type",
        "event_date",
        "amount",
        "requirements",
        "response_deadline",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.SCHOOL_COMMUNICATION]
    assert _field_names(spec) == expected
    assert EdgeType.STATES in spec.target_edge_types
    assert EdgeType.IMPLIES in spec.target_edge_types


def test_permission_slip_fields_match_spec() -> None:
    # §5.4.2: "issuing body · subject person · what is being consented to ·
    # required signatory type · return deadline · attached requirements
    # (payment, medical info, emergency contact)"
    expected = {
        "issuing_body",
        "subject_person",
        "consent_description",
        "required_signatory_type",
        "return_deadline",
        "attached_requirement_payment",
        "attached_requirement_medical_info",
        "attached_requirement_emergency_contact",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.PERMISSION_SLIP]
    assert _field_names(spec) == expected
    assert EdgeType.OWNED_BY in spec.target_edge_types


def test_attendance_register_fields_match_spec() -> None:
    # §5.4.2: "staff member · month · per-day presence marks · leave
    # annotations · advance notations in margins"
    expected = {
        "staff_member",
        "month",
        "per_day_presence_marks",
        "leave_annotations",
        "advance_notations_margin",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.ATTENDANCE_REGISTER]
    assert _field_names(spec) == expected
    assert spec.target_node_types == ("PERSON",)


def test_bank_statement_fields_match_spec() -> None:
    # §5.4.2: "account · period · per-transaction (date, description,
    # amount, direction, balance) · opening/closing balance"
    expected = {"account", "period_start", "period_end", "transactions", "opening_balance", "closing_balance"}
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.BANK_STATEMENT]
    assert _field_names(spec) == expected
    assert "upi_sms_alert_accuracy" in spec.verification_duties


def test_upi_sms_alert_fields_match_spec() -> None:
    # §5.4.2: "amount · direction · counterparty VPA or merchant string ·
    # reference · timestamp · account last-4"
    expected = {
        "amount",
        "direction",
        "counterparty_vpa_or_merchant",
        "reference_number",
        "timestamp",
        "account_last4",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.UPI_SMS_ALERT]
    assert _field_names(spec) == expected
    counterparty_field = next(f for f in spec.field_schema if f.name == "counterparty_vpa_or_merchant")
    assert counterparty_field.confidence_floor < 0.55, "merchant strings are notoriously opaque, spec §5.4.2"


def test_medical_document_fields_match_spec() -> None:
    # §5.4.2: "patient · provider · date · document type · appointment/
    # follow-up dates · medication names and schedules · stated
    # restrictions"
    expected = {
        "patient",
        "provider",
        "document_date",
        "document_type",
        "appointment_or_followup_dates",
        "medication_names_and_schedules",
        "stated_restrictions",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.MEDICAL_DOCUMENT]
    assert _field_names(spec) == expected
    assert "clinical_interpretation" not in " ".join(f.name for f in spec.field_schema)


def test_insurance_document_fields_match_spec() -> None:
    # §5.4.2: "insurer · policy number · covered persons · coverage type
    # and limits · premium and due date · renewal date · exclusions"
    expected = {
        "insurer",
        "policy_number",
        "covered_persons",
        "coverage_type",
        "coverage_limits",
        "premium",
        "premium_due_date",
        "renewal_date",
        "exclusions",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.INSURANCE_DOCUMENT]
    assert _field_names(spec) == expected


def test_warranty_fields_match_spec() -> None:
    # §5.4.2: "product · purchase date · warranty period and expiry ·
    # coverage terms · claim process · serial number"
    expected = {
        "product",
        "purchase_date",
        "warranty_period",
        "warranty_expiry",
        "coverage_terms",
        "claim_process",
        "serial_number",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.WARRANTY]
    assert _field_names(spec) == expected


def test_government_notice_fields_match_spec() -> None:
    # §5.4.2: "issuing body · reference · subject · required action ·
    # deadline · penalty for non-compliance"
    expected = {
        "issuing_body",
        "reference",
        "subject",
        "required_action",
        "deadline",
        "penalty_for_noncompliance",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.GOVERNMENT_NOTICE]
    assert _field_names(spec) == expected


def test_quote_estimate_fields_match_spec() -> None:
    # §5.4.2: "provider · scope of work · line-item costs · validity
    # period · terms"
    expected = {"provider", "scope_of_work", "line_item_costs", "validity_period", "terms"}
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.QUOTE_ESTIMATE]
    assert _field_names(spec) == expected
    assert spec.target_node_types == ("PROVIDER", "BRANCH")


def test_chat_thread_fields_match_spec() -> None:
    # §5.4.2: "participants · timestamps · message content · embedded
    # commitments, complaints, leave notifications, intentions"
    expected = {
        "participants",
        "timestamps",
        "message_content",
        "embedded_commitments",
        "complaints",
        "leave_notifications",
        "intentions",
    }
    spec = DOCUMENT_TYPE_SPECS_BY_ID[type_id.CHAT_THREAD]
    assert _field_names(spec) == expected
    assert spec.target_node_types == ("OBLIGATION",)
