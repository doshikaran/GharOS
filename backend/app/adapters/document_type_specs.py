"""The fourteen `DocumentTypeSpec` entries of the Document-Type Registry.

Source of truth: `GharOS_Build_Spec_v2.md` §5.4.2, read in full for this
phase — every field, detection signal, node type, and edge listed below is
traced to that section, not invented. Where §5.4.2 gives a type no
explicit "Detection:" or "Edges:" line, this module says so in that type's
builder function and derives the minimum defensible signal from the
fields/nodes the spec *does* name for that type (documented inline, never
silently filled in) — the same "state the gap, don't paper over it"
discipline `app/graph/integrity_checker.py`'s
`_NEVER_EDGE_CONNECTED_NODE_TYPE_NAMES` already sets for this codebase.

**One deliberate exception to the ~500-line file guideline:** this module
is fourteen independent, spec-traced data entries — splitting them across
fourteen files would scatter what a reviewer needs to cross-check against
one spec section into fourteen open tabs, for no behavioural gain (there
is no shared runtime logic here to isolate, only data). Kept as one file,
organised as one private builder function per type plus the two exported
aggregates at the bottom, per this phase's explicit instruction that this
organisation is acceptable.

**Known registry gap, flagged rather than papered over (see WARRANTY
below):** spec §5.4.2 says a WARRANTY document "links back to the
originating receipt's PURCHASE_ITEM," but `contracts.graph_types.EdgeType`
(frozen, CTO-owned) has no edge type whose endpoints are
(OBLIGATION, PURCHASE_ITEM) or similar. This is reported to the CTO in
this phase's report, not worked around by repurposing an unrelated edge
type to mean something spec-3-1 never assigned it.

Confidence floors are per-field, hand-set from the spec's own field
descriptions (financially/legally load-bearing fields get higher floors
than descriptive ones), with one binding numeric constraint from spec
§5.4.2 itself: ATTENDANCE_REGISTER's floors are **the strictest in the
registry** ("handwriting misread directly causes wrong salary payment...
below threshold, present the image to the human, never infer"). Every
floor in every other type's schema in this module is kept strictly below
`_ATTENDANCE_MIN_FLOOR` — enforced by a property-based test in
`test_document_type_specs.py`, not just eyeballed here.
"""

from __future__ import annotations

from contracts.graph_types import DocumentTypeSpec, EdgeType, FieldSchema

from app.adapters import document_type_ids as type_id

_ATTENDANCE_MIN_FLOOR = 0.90
"""Every field floor on ATTENDANCE_REGISTER is >= this. Every field floor
on every *other* type in this module is < this. See module docstring."""


# ---------------------------------------------------------------------------
# 1. RECEIPT / ITEMISED BILL
# ---------------------------------------------------------------------------


def _receipt_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "RECEIPT / ITEMISED BILL" — full explicit Detection:/
    Schema:/Nodes:/Edges: block, transcribed directly. The strongest
    verification document in the system (spec §5.5)."""
    return DocumentTypeSpec(
        type_id=type_id.RECEIPT,
        detection_signals=(
            "merchant_header",
            "line_item_block",
            "total_line",
            "payment_method_line",
            "tax_lines",
        ),
        field_schema=(
            FieldSchema(name="merchant_name", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="merchant_category", field_type="string", required=True, confidence_floor=0.60),
            FieldSchema(
                name="transaction_datetime", field_type="datetime", required=True, confidence_floor=0.75
            ),
            FieldSchema(name="payment_method", field_type="string", required=False, confidence_floor=0.50),
            FieldSchema(name="payment_last4", field_type="string", required=False, confidence_floor=0.60),
            FieldSchema(
                name="line_items", field_type="list[line_item]", required=True, confidence_floor=0.70
            ),
            FieldSchema(name="subtotal", field_type="number", required=False, confidence_floor=0.60),
            FieldSchema(name="tax", field_type="number", required=False, confidence_floor=0.60),
            FieldSchema(name="discounts", field_type="number", required=False, confidence_floor=0.50),
            FieldSchema(name="total", field_type="number", required=True, confidence_floor=0.80),
            FieldSchema(
                name="loyalty_account_id", field_type="string", required=False, confidence_floor=0.50
            ),
        ),
        target_node_types=("LEDGER_EVENT", "PURCHASE_ITEM"),
        target_edge_types=(
            EdgeType.LINE_ITEM_OF,
            EdgeType.OWED_TO,
            EdgeType.DISCHARGES,
            EdgeType.VERIFIES,
            EdgeType.CONTRADICTS,
            EdgeType.SUBSTITUTES,
            EdgeType.EVIDENCES_EFFORT,
            EdgeType.BELONGS_TO,
        ),
        downstream_subsystems=(
            "ledger_reconciliation",
            "constraint_verification",
            "consequence_engine",
            "fair_allocator",
        ),
        verification_duties=(
            "constraint_compliance",
            "obligation_discharge",
            "planned_vs_actual_purchases",
            "who_did_the_work",
        ),
    )


# ---------------------------------------------------------------------------
# 2. UTILITY / SERVICE BILL
# ---------------------------------------------------------------------------


def _utility_bill_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "UTILITY / SERVICE BILL". Nodes: LEDGER_EVENT (due),
    RECURRING_COMMITMENT (create or match) — spec's own Nodes: line does
    NOT list OBLIGATION here; the "creates a payment obligation" language
    in spec's prose is the Consequence Engine's (Phase 4) downstream
    trigger effect, not something this Phase 3 extraction strategy
    produces directly (see `downstream_subsystems`: "consequence_engine").
    `target_edge_types` therefore has no `STATES` — there is no OBLIGATION
    node in this entry's own `target_node_types` for a `states` edge to
    target; adding one anyway (an earlier version of this entry did)
    silently implied a node this strategy never actually writes. Caught
    and corrected in Phase 3's CTO gate review."""
    return DocumentTypeSpec(
        type_id=type_id.UTILITY_BILL,
        detection_signals=("account_number", "billing_period", "due_date", "consumption_block"),
        field_schema=(
            FieldSchema(name="provider", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="account_identifier", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="billing_period_start", field_type="date", required=True, confidence_floor=0.70),
            FieldSchema(name="billing_period_end", field_type="date", required=True, confidence_floor=0.70),
            FieldSchema(
                name="consumption_reading", field_type="number", required=False, confidence_floor=0.60
            ),
            FieldSchema(name="consumption_units", field_type="string", required=False, confidence_floor=0.55),
            FieldSchema(name="amount_due", field_type="number", required=True, confidence_floor=0.80),
            FieldSchema(name="due_date", field_type="date", required=True, confidence_floor=0.80),
            FieldSchema(name="late_fee_terms", field_type="string", required=False, confidence_floor=0.50),
            FieldSchema(name="prior_balance", field_type="number", required=False, confidence_floor=0.55),
        ),
        target_node_types=("LEDGER_EVENT", "RECURRING_COMMITMENT"),
        target_edge_types=(EdgeType.BELONGS_TO, EdgeType.OWED_TO),
        downstream_subsystems=("ledger_due_tracking", "silent_hike_detection", "consequence_engine"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 3. SOCIETY / HOA MAINTENANCE NOTICE
# ---------------------------------------------------------------------------


def _society_notice_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "SOCIETY / HOA MAINTENANCE NOTICE". Nodes are
    conditional in the spec's own wording ("LEDGER_EVENT (if dues)",
    "CONSTRAINT (if a rule change)") — kept as a superset here since a
    `DocumentTypeSpec` is registered once per `type_id`, not once per
    notice instance; which of the three actually gets written is the
    `ExtractionStrategy`'s (E2's) runtime decision per document. `STATES`
    added alongside the spec's literal `owed_to`/`constrains` pair for the
    same literally-printed-due-date reasoning as `_utility_bill_spec`."""
    return DocumentTypeSpec(
        type_id=type_id.SOCIETY_NOTICE,
        detection_signals=("society_letterhead", "unit_reference", "circular_or_notice_framing"),
        field_schema=(
            FieldSchema(name="society_name", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="unit", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="notice_type", field_type="string", required=True, confidence_floor=0.65),
            FieldSchema(name="amount", field_type="number", required=False, confidence_floor=0.75),
            FieldSchema(name="due_date", field_type="date", required=False, confidence_floor=0.75),
            FieldSchema(name="effective_date", field_type="date", required=False, confidence_floor=0.65),
            FieldSchema(name="contact", field_type="string", required=False, confidence_floor=0.50),
        ),
        target_node_types=("LEDGER_EVENT", "OBLIGATION", "CONSTRAINT"),
        target_edge_types=(EdgeType.OWED_TO, EdgeType.CONSTRAINS, EdgeType.STATES),
        downstream_subsystems=("ledger", "consequence_engine", "constraint_learner"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 4. SCHOOL / INSTITUTIONAL COMMUNICATION
# ---------------------------------------------------------------------------


def _school_communication_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "SCHOOL / INSTITUTIONAL COMMUNICATION" — full explicit
    block, transcribed directly. Spec's own name for this: "the
    implication-rich case" — multiple OBLIGATIONs per document."""
    return DocumentTypeSpec(
        type_id=type_id.SCHOOL_COMMUNICATION,
        detection_signals=("school_identifiers", "student_name", "academic_framing"),
        field_schema=(
            FieldSchema(name="institution", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="student", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="communication_type", field_type="string", required=True, confidence_floor=0.65),
            FieldSchema(name="event_date", field_type="date", required=False, confidence_floor=0.70),
            FieldSchema(name="amount", field_type="number", required=False, confidence_floor=0.75),
            FieldSchema(
                name="requirements", field_type="list[string]", required=False, confidence_floor=0.60
            ),
            FieldSchema(name="response_deadline", field_type="date", required=False, confidence_floor=0.75),
        ),
        target_node_types=("OBLIGATION", "CONSTRAINT"),
        target_edge_types=(EdgeType.STATES, EdgeType.IMPLIES, EdgeType.BENEFITS, EdgeType.VIOLATES),
        downstream_subsystems=("consequence_engine", "ledger_fees", "outbound_concierge"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 5. PERMISSION SLIP / CONSENT FORM
# ---------------------------------------------------------------------------


def _permission_slip_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "PERMISSION SLIP / CONSENT FORM". `STATES` added
    alongside the spec's literal `owned_by`/`depends_on` pair for the
    same literally-printed-deadline reasoning as `_utility_bill_spec`
    (the return deadline is printed text, not inferred)."""
    return DocumentTypeSpec(
        type_id=type_id.PERMISSION_SLIP,
        detection_signals=("signature_block", "consent_language", "tear_off_section"),
        field_schema=(
            FieldSchema(name="issuing_body", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="subject_person", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(
                name="consent_description", field_type="string", required=True, confidence_floor=0.65
            ),
            FieldSchema(
                name="required_signatory_type", field_type="string", required=True, confidence_floor=0.70
            ),
            FieldSchema(name="return_deadline", field_type="date", required=True, confidence_floor=0.75),
            FieldSchema(
                name="attached_requirement_payment",
                field_type="number",
                required=False,
                confidence_floor=0.60,
            ),
            FieldSchema(
                name="attached_requirement_medical_info",
                field_type="string",
                required=False,
                confidence_floor=0.60,
            ),
            FieldSchema(
                name="attached_requirement_emergency_contact",
                field_type="string",
                required=False,
                confidence_floor=0.60,
            ),
        ),
        target_node_types=("OBLIGATION",),
        target_edge_types=(EdgeType.OWNED_BY, EdgeType.DEPENDS_ON, EdgeType.STATES),
        downstream_subsystems=("consequence_engine", "form_prefill"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 6. ATTENDANCE REGISTER (handwritten) — strictest floors in the registry
# ---------------------------------------------------------------------------


def _attendance_register_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "ATTENDANCE REGISTER" — explicitly the strictest
    confidence floors in the registry ("handwriting misread directly
    causes wrong salary payment... below threshold, present the image to
    the human, never infer"). Every floor here is >= `_ATTENDANCE_MIN_FLOOR`
    and every floor on every other type in this module is below it —
    checked by `test_document_type_specs.py`.

    `target_node_types`/`target_edge_types` updated Phase 7 (ADR-013,
    DEBT-004's repayment): `AttendanceRecord` and `attendance_of` now
    exist for real, and `attendance_register_strategy.py` (E2) writes
    both instead of only summarising into `verification_findings`."""
    return DocumentTypeSpec(
        type_id=type_id.ATTENDANCE_REGISTER,
        detection_signals=("grid_tabular_structure", "date_column", "name_rows", "tick_or_cross_marks"),
        field_schema=(
            FieldSchema(name="staff_member", field_type="string", required=True, confidence_floor=0.92),
            FieldSchema(name="month", field_type="string", required=True, confidence_floor=0.90),
            FieldSchema(
                name="per_day_presence_marks",
                field_type="list[presence_mark]",
                required=True,
                confidence_floor=0.95,
            ),
            FieldSchema(
                name="leave_annotations", field_type="list[string]", required=False, confidence_floor=0.90
            ),
            FieldSchema(
                name="advance_notations_margin",
                field_type="list[string]",
                required=False,
                confidence_floor=0.90,
            ),
        ),
        target_node_types=("PERSON", "ATTENDANCE_RECORD"),
        target_edge_types=(EdgeType.ATTENDANCE_OF,),
        downstream_subsystems=("ledger_payroll",),
        verification_duties=("attendance_vs_chat_leave_messages_consistency",),
    )


# ---------------------------------------------------------------------------
# 7. BANK / CARD STATEMENT
# ---------------------------------------------------------------------------


def _bank_statement_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "BANK / CARD STATEMENT" — full explicit block,
    transcribed directly. The reconciliation ground truth (spec §5.5)."""
    return DocumentTypeSpec(
        type_id=type_id.BANK_STATEMENT,
        detection_signals=("account_header", "transaction_table", "period", "balances"),
        field_schema=(
            FieldSchema(name="account", field_type="string", required=True, confidence_floor=0.75),
            FieldSchema(name="period_start", field_type="date", required=True, confidence_floor=0.75),
            FieldSchema(name="period_end", field_type="date", required=True, confidence_floor=0.75),
            FieldSchema(
                name="transactions", field_type="list[transaction]", required=True, confidence_floor=0.80
            ),
            FieldSchema(name="opening_balance", field_type="number", required=True, confidence_floor=0.70),
            FieldSchema(name="closing_balance", field_type="number", required=True, confidence_floor=0.70),
        ),
        target_node_types=("LEDGER_EVENT",),
        target_edge_types=(EdgeType.BELONGS_TO, EdgeType.OWED_TO),
        downstream_subsystems=("ledger_reconciliation", "leakage_detection", "recurring_series_discovery"),
        verification_duties=("upi_sms_alert_accuracy", "payment_clearance_confirmation"),
    )


# ---------------------------------------------------------------------------
# 8. UPI / PAYMENT SMS ALERT
# ---------------------------------------------------------------------------


def _upi_sms_alert_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "UPI / PAYMENT SMS ALERT". `counterparty_vpa_or_merchant`
    is given a deliberately *low* floor (0.45, not raised to match the
    other required fields) — spec's own note: merchant strings are
    "notoriously opaque ('PAYTM*XXXXX')... low-confidence merchant
    resolution must not drive a cancellation recommendation on its own."
    The low floor here is what lets that field surface as low-confidence
    rather than getting silently discarded as "below floor" before any
    downstream rule can apply spec's actual policy for it."""
    return DocumentTypeSpec(
        type_id=type_id.UPI_SMS_ALERT,
        detection_signals=("short_structured_text", "amount", "vpa_or_merchant", "reference_number"),
        field_schema=(
            FieldSchema(name="amount", field_type="number", required=True, confidence_floor=0.80),
            FieldSchema(name="direction", field_type="string", required=True, confidence_floor=0.80),
            FieldSchema(
                name="counterparty_vpa_or_merchant", field_type="string", required=True, confidence_floor=0.45
            ),
            FieldSchema(name="reference_number", field_type="string", required=False, confidence_floor=0.60),
            FieldSchema(name="timestamp", field_type="datetime", required=True, confidence_floor=0.75),
            FieldSchema(name="account_last4", field_type="string", required=False, confidence_floor=0.60),
        ),
        target_node_types=("LEDGER_EVENT",),
        target_edge_types=(EdgeType.BELONGS_TO,),
        downstream_subsystems=("ledger", "mandate_detection"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 9. MEDICAL DOCUMENT
# ---------------------------------------------------------------------------


def _medical_document_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "MEDICAL DOCUMENT". `STATES` added alongside the spec's
    literal `constrains`/`benefits` pair for the same literally-printed-
    date reasoning as `_utility_bill_spec` (appointment/follow-up dates
    are printed text). **Hard rule carried forward verbatim into this
    registry entry's field schema:** `stated_restrictions` captures
    restrictions exactly as printed — this module's schema has no field
    for a derived/inferred medical interpretation, and none may ever be
    added (spec §5.4.2: "the system never interprets clinical meaning,
    never advises, never adjusts medication")."""
    return DocumentTypeSpec(
        type_id=type_id.MEDICAL_DOCUMENT,
        detection_signals=("clinical_letterhead", "patient_identifiers", "clinical_terminology"),
        field_schema=(
            FieldSchema(name="patient", field_type="string", required=True, confidence_floor=0.75),
            FieldSchema(name="provider", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="document_date", field_type="date", required=True, confidence_floor=0.70),
            FieldSchema(name="document_type", field_type="string", required=True, confidence_floor=0.65),
            FieldSchema(
                name="appointment_or_followup_dates",
                field_type="list[date]",
                required=False,
                confidence_floor=0.75,
            ),
            FieldSchema(
                name="medication_names_and_schedules",
                field_type="list[string]",
                required=False,
                confidence_floor=0.70,
            ),
            FieldSchema(
                name="stated_restrictions", field_type="list[string]", required=False, confidence_floor=0.80
            ),
        ),
        target_node_types=("OBLIGATION", "CONSTRAINT"),
        target_edge_types=(EdgeType.CONSTRAINS, EdgeType.BENEFITS, EdgeType.STATES),
        downstream_subsystems=("consequence_engine", "outbound_concierge", "council_care_specialist"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 10. INSURANCE DOCUMENT
# ---------------------------------------------------------------------------


def _insurance_document_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "INSURANCE DOCUMENT" gives a Schema:/Nodes:/Triggers:
    block but, unlike RECEIPT or BANK_STATEMENT, no explicit "Detection:"
    or "Edges:" line. `detection_signals` here is derived from the
    schema's own named fields (policy number, insurer, premium/due date,
    renewal date) rather than invented document-appearance cues the spec
    never states. Nodes: RECURRING_COMMITMENT, OBLIGATION (renewal),
    CONSTRAINT — spec's own Nodes: line has no LEDGER_EVENT here (premium
    payments show up as LEDGER_EVENTs when a bank statement or UPI alert
    is later extracted, not from the policy document itself), so
    `target_edge_types` has no `BELONGS_TO` (LEDGER_EVENT -> RECURRING_
    COMMITMENT — its FROM-side node isn't produced by this entry). An
    earlier version of this entry included it by analogy to UTILITY_BILL;
    caught and corrected in Phase 3's CTO gate review. `STATES` remains —
    OBLIGATION *is* in `target_node_types` here, and the renewal date is
    printed text."""
    return DocumentTypeSpec(
        type_id=type_id.INSURANCE_DOCUMENT,
        detection_signals=(
            "policy_number_field",
            "insurer_name_field",
            "premium_and_due_date_fields",
            "renewal_date_field",
        ),
        field_schema=(
            FieldSchema(name="insurer", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="policy_number", field_type="string", required=True, confidence_floor=0.75),
            FieldSchema(
                name="covered_persons", field_type="list[string]", required=True, confidence_floor=0.65
            ),
            FieldSchema(name="coverage_type", field_type="string", required=True, confidence_floor=0.65),
            FieldSchema(name="coverage_limits", field_type="number", required=False, confidence_floor=0.65),
            FieldSchema(name="premium", field_type="number", required=True, confidence_floor=0.75),
            FieldSchema(name="premium_due_date", field_type="date", required=True, confidence_floor=0.75),
            FieldSchema(name="renewal_date", field_type="date", required=True, confidence_floor=0.75),
            FieldSchema(name="exclusions", field_type="list[string]", required=False, confidence_floor=0.60),
        ),
        target_node_types=("RECURRING_COMMITMENT", "OBLIGATION", "CONSTRAINT"),
        target_edge_types=(EdgeType.STATES,),
        downstream_subsystems=("ledger", "council"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 11. WARRANTY / PURCHASE PROTECTION
# ---------------------------------------------------------------------------


def _warranty_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "WARRANTY / PURCHASE PROTECTION" gives a Schema:/Nodes:
    block but, like INSURANCE_DOCUMENT, no explicit "Detection:" line —
    derived the same way, from the schema's own named fields.

    **Registry gap resolved (ADR-009):** spec's text says a warranty
    document "links back to the originating RECEIPT's PURCHASE_ITEM — this
    is why receipt line-item extraction matters months later." No edge type
    encoded this relationship at the time this file was first written —
    flagged to the CTO, who added `EdgeType.COVERS` (OBLIGATION ->
    PURCHASE_ITEM) in ADR-009. `target_edge_types` below reflects that
    addition."""
    return DocumentTypeSpec(
        type_id=type_id.WARRANTY,
        detection_signals=(
            "product_description_field",
            "warranty_period_or_expiry_field",
            "serial_number_field",
        ),
        field_schema=(
            FieldSchema(name="product", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="purchase_date", field_type="date", required=True, confidence_floor=0.70),
            FieldSchema(name="warranty_period", field_type="string", required=True, confidence_floor=0.65),
            FieldSchema(name="warranty_expiry", field_type="date", required=True, confidence_floor=0.75),
            FieldSchema(name="coverage_terms", field_type="string", required=False, confidence_floor=0.55),
            FieldSchema(name="claim_process", field_type="string", required=False, confidence_floor=0.50),
            FieldSchema(name="serial_number", field_type="string", required=False, confidence_floor=0.65),
        ),
        target_node_types=("OBLIGATION",),
        target_edge_types=(EdgeType.STATES, EdgeType.COVERS),
        downstream_subsystems=("ledger",),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 12. GOVERNMENT / LEGAL NOTICE
# ---------------------------------------------------------------------------


def _government_notice_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "GOVERNMENT / LEGAL NOTICE" gives a Schema:/Nodes:
    block, no explicit "Detection:" or "Edges:" line — derived from the
    schema's own named fields, `STATES` added for the printed deadline,
    same reasoning as `_utility_bill_spec`."""
    return DocumentTypeSpec(
        type_id=type_id.GOVERNMENT_NOTICE,
        detection_signals=("issuing_body_field", "reference_number_field", "deadline_field"),
        field_schema=(
            FieldSchema(name="issuing_body", field_type="string", required=True, confidence_floor=0.75),
            FieldSchema(name="reference", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="subject", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="required_action", field_type="string", required=True, confidence_floor=0.75),
            FieldSchema(name="deadline", field_type="date", required=True, confidence_floor=0.80),
            FieldSchema(
                name="penalty_for_noncompliance", field_type="string", required=False, confidence_floor=0.60
            ),
        ),
        target_node_types=("OBLIGATION",),
        target_edge_types=(EdgeType.STATES,),
        downstream_subsystems=("consequence_engine", "escalation"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 13. QUOTE / ESTIMATE
# ---------------------------------------------------------------------------


def _quote_estimate_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "QUOTE / ESTIMATE" gives a Schema:/Nodes:/Triggers:
    block, no explicit "Detection:" or "Edges:" line — detection derived
    from the schema's own named fields. `target_edge_types` uses
    `GROUNDED_IN`: spec §5.3's edge table states this edge's meaning
    exactly — "BRANCH | POSITION -> SOURCE_DOCUMENT | external ref |
    Evidence" — which is precisely what a quote becomes when it is part
    of an active DECISION's BRANCH (this type's own Nodes: line names
    BRANCH as conditional on that), so this is a literal application of
    an already-defined general edge, not an invented one."""
    return DocumentTypeSpec(
        type_id=type_id.QUOTE_ESTIMATE,
        detection_signals=("provider_field", "line_item_costs_block", "validity_period_field"),
        field_schema=(
            FieldSchema(name="provider", field_type="string", required=True, confidence_floor=0.70),
            FieldSchema(name="scope_of_work", field_type="string", required=True, confidence_floor=0.65),
            FieldSchema(
                name="line_item_costs", field_type="list[line_item]", required=True, confidence_floor=0.65
            ),
            FieldSchema(name="validity_period", field_type="string", required=False, confidence_floor=0.55),
            FieldSchema(name="terms", field_type="string", required=False, confidence_floor=0.50),
        ),
        target_node_types=("PROVIDER", "BRANCH"),
        target_edge_types=(EdgeType.GROUNDED_IN,),
        downstream_subsystems=("council_comparison", "outbound_concierge_quote_gathering"),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# 14. CHAT / MESSAGE THREAD
# ---------------------------------------------------------------------------


def _chat_thread_spec() -> DocumentTypeSpec:
    """Spec §5.4.2 "CHAT / MESSAGE THREAD" — Schema:/Nodes:/Triggers:
    given, no explicit "Detection:" or "Edges:" line. Detection derived
    from the schema's own named fields (participants, per-message
    timestamps, code-mixed content).

    `target_node_types` is `(OBLIGATION,)` only: spec's Nodes: line also
    names "intention captures, valuation signals, staff leave records,"
    but none of those are names of any of the 16 actual node types (spec
    §5.2) — they describe *what a chat message can evidence*, realised
    downstream as PERSON valuation-profile updates or LEDGER_EVENT-
    adjacent leave records, not as a distinct new graph node type this
    entry could name. Only OBLIGATION is an actual node type name here,
    so only it is listed — the same "don't invent" discipline as fields.

    `target_edge_types` is `(STATES,)`: a casual chat commitment
    ("I'll pick her up Friday") is text literally present in the message,
    and A3/A4 extraction is forbidden from inferring anything not
    literally present (spec §15.2 A3) — deriving that this stated
    commitment constitutes an *implied* household obligation is
    Phase 4's Implication Agent's (A12) job, not this registry entry's."""
    return DocumentTypeSpec(
        type_id=type_id.CHAT_THREAD,
        detection_signals=(
            "multi_participant_message_format",
            "per_message_timestamp",
            "code_mixed_or_colloquial_text",
        ),
        field_schema=(
            FieldSchema(name="participants", field_type="list[string]", required=True, confidence_floor=0.65),
            FieldSchema(name="timestamps", field_type="list[datetime]", required=True, confidence_floor=0.60),
            FieldSchema(
                name="message_content", field_type="list[string]", required=True, confidence_floor=0.55
            ),
            FieldSchema(
                name="embedded_commitments", field_type="list[string]", required=False, confidence_floor=0.55
            ),
            FieldSchema(name="complaints", field_type="list[string]", required=False, confidence_floor=0.50),
            FieldSchema(
                name="leave_notifications", field_type="list[string]", required=False, confidence_floor=0.60
            ),
            FieldSchema(name="intentions", field_type="list[string]", required=False, confidence_floor=0.50),
        ),
        target_node_types=("OBLIGATION",),
        target_edge_types=(EdgeType.STATES,),
        downstream_subsystems=("all_subsystems",),
        verification_duties=(),
    )


# ---------------------------------------------------------------------------
# Aggregates
# ---------------------------------------------------------------------------

ALL_DOCUMENT_TYPE_SPECS: tuple[DocumentTypeSpec, ...] = (
    _receipt_spec(),
    _utility_bill_spec(),
    _society_notice_spec(),
    _school_communication_spec(),
    _permission_slip_spec(),
    _attendance_register_spec(),
    _bank_statement_spec(),
    _upi_sms_alert_spec(),
    _medical_document_spec(),
    _insurance_document_spec(),
    _warranty_spec(),
    _government_notice_spec(),
    _quote_estimate_spec(),
    _chat_thread_spec(),
)
"""All fourteen `DocumentTypeSpec` entries, built once at import time (they
are frozen dataclasses over plain data — no I/O, no randomness, safe to
build eagerly). Order matches `document_type_ids.ALL_TYPE_IDS`."""

DOCUMENT_TYPE_SPECS_BY_ID: dict[str, DocumentTypeSpec] = {
    spec.type_id: spec for spec in ALL_DOCUMENT_TYPE_SPECS
}
"""Convenience lookup — `DocumentTypeRegistry` (in `document_registry.py`)
uses `ALL_DOCUMENT_TYPE_SPECS` directly at composition-root wiring time;
this dict exists for call sites (and tests) that just need one type's spec
without constructing a registry."""


__all__ = ["ALL_DOCUMENT_TYPE_SPECS", "DOCUMENT_TYPE_SPECS_BY_ID"]
