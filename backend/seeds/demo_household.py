"""A small, realistic-but-synthetic demo household (PHASES.md Phase 1 work
item 8, extended Phase 7 for ADR-013/DEBT-004's `AttendanceRecord`, and
Phase 8 for ADR-014's `ValuationProfile`) — enough breadth to exercise
every one of the 18 node types and most of the 35 edge types (see
`SeedResult.supersession` and this module's bottom-of-file note on
`argued_by`), and to prove `unexplained` returns empty and the integrity
checker is clean on real seeded data.

This is deliberately *not* the full 8-12-document demo dataset from spec
§26 — that is Phase 15's job (Demo Hardening). This is Phase 1's proof
that the graph machinery itself is correct end-to-end on non-trivial data:
a household with four PERSONs (adult/child/elder/staff), two CONSTRAINTs
(one hard), several OBLIGATIONs including one that gets superseded (real
versioning, not just a unit test), a RECURRING_COMMITMENT, several
LEDGER_EVENTs (including one ADVANCE, per ADR-013's rule that real advance
amounts live only on LEDGER_EVENT, never parsed from an
ATTENDANCE_RECORD's `advance_notations`), five PURCHASE_ITEMs covering
`verifies`, `contradicts`, and `substitutes`, a DECISION with two
BRANCHes and two COUNCIL_POSITIONs, an OUTCOME, four SOURCE_DOCUMENTs, one
ACTION_RECORD, one APPROVAL_REQUEST, one PATTERN, one ATTENDANCE_RECORD
(`attendance_of` to the staff PERSON), and one VALUATION_PROFILE
(`valuation_of` to Priya — ADR-014's cardinal cost matrix over three real
seeded OBLIGATIONs).

**Historical note, corrected — kept for continuity, not because the gap
is still real:** Phase 1's original version of this dataset flagged that
`contracts.graph_types.EdgeType` had no edge type connecting ACTION_RECORD
or APPROVAL_REQUEST to anything else in the graph, making the one of each
seeded here necessarily edge-orphans. That gap was DEBT-002, repaid in
Phase 5 (ADR-012: `acts_on`, `authorizes`, `approved_by`) — `action_record1`
and `approval_request1` below now carry all three edges for real
(`e-acts_on-action1-o4`, `e-authorizes-approval1-action1`,
`e-approved_by-approval1-priya`), exactly mirroring what a live
`ApprovalGate.approve_and_execute` run produces. `FirestoreGraphIntegrityChecker`
still special-cases APPROVAL_REQUEST (a `PENDING`/`REJECTED`/`EXPIRED`
request is legitimately edge-orphaned by design — see that module's own
docstring) but no longer ACTION_RECORD, which is now always edge-connected
by construction.

**Also deliberately not used:** `argued_by` (COUNCIL_POSITION -> AGENT).
`AGENT` is not one of the 18 node types — agents are referenced by
`AgentId` (a plain string) on `Provenance.deriving_agent` and
`CouncilPosition.held_by_agent`, never stored as graph nodes — so this
edge type has no resolvable node collection to point at. Using it here
would create a permanently-dangling edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from contracts.graph_types import (
    ActionRecord,
    AgentId,
    ApprovalRequest,
    ApprovalStatus,
    AttendanceRecord,
    Branch,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    CouncilPosition,
    Decision,
    DecisionStatus,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    LanguageProfile,
    LedgerEvent,
    LedgerEventKind,
    LiteracyMode,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Pattern,
    Person,
    PersonRole,
    Provenance,
    Provider,
    PurchaseItem,
    RecurringCommitment,
    SourceDocument,
    SourceRef,
    ValuationProfile,
    Vendor,
)

NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)
"""Fixed seed reference time — matches `currentDate` for this session so
`due_at`/`occurred_at` windows in seed data and in tests that load it stay
in sync without either side hardcoding the other."""

_HOUSEHOLD_AGENT = AgentId("A7")
"""Graph Builder — spec §15, the agent that would durably write extracted
graph nodes/edges in production. Seed data uses the same agent id a real
write would, rather than an invented "seed" identity, since seeded nodes
are meant to be indistinguishable in shape from ingested ones."""


def _prov(
    *,
    source_document_id: str,
    region: str,
    derivation: Derivation = Derivation.EXTRACTED,
    confidence: float = 0.92,
) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=SourceRef(source_document_id=NodeId(source_document_id), region=region),
        confidence=confidence,
        deriving_agent=_HOUSEHOLD_AGENT,
        created_at=NOW,
    )


def _ambiguous_prov(*, confidence: float) -> Provenance:
    """For PATTERN nodes with multiple contributing OUTCOMEs and no single
    source (spec §5.6 — the one legitimate `source_ref=None` case)."""
    return Provenance(
        derivation=Derivation.AMBIGUOUS,
        source_ref=None,
        confidence=confidence,
        deriving_agent=_HOUSEHOLD_AGENT,
        created_at=NOW,
    )


def _language_profile(primary: str) -> LanguageProfile:
    return LanguageProfile(
        primary_language=primary,
        languages_understood=("hi", "en"),
        script_preference="devanagari" if primary == "hi" else "latin",
        code_mixing_profile="hi-en",
        formality_preference="informal",
        literacy_mode=LiteracyMode.BOTH,
    )


@dataclass(frozen=True, slots=True)
class SeedResult:
    """Everything `seed_loader.load_demo_household` needs to write, plus
    the one supersession step it must perform *after* the initial writes
    (the old obligation must exist before it can be superseded)."""

    nodes: tuple[object, ...]
    edges: tuple[Edge, ...]
    supersession: tuple[NodeId, Obligation]
    """`(old_obligation_id, new_obligation)` — proves real versioning
    end-to-end on seeded data, not just in a unit test."""


def build_demo_household() -> SeedResult:
    """Builds (but does not write) the full demo household graph."""
    nodes: list[object] = []
    edges: list[Edge] = []

    # -- source documents -----------------------------------------------------

    d1_receipt = SourceDocument(
        id=NodeId("doc-freshmart-receipt"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="whole-document"),
        channel="upload",
        raw_payload_ref="receipts/freshmart-2026-08-20.jpg",
        document_type="RECEIPT",
        ingested_at=NOW - timedelta(days=2),
        original_language="en",
    )
    d2_school_chat = SourceDocument(
        id=NodeId("doc-school-whatsapp"),
        provenance=_prov(source_document_id="doc-school-whatsapp", region="whole-document"),
        channel="whatsapp",
        raw_payload_ref="chats/school-group-2026-08-21.json",
        document_type="CHAT_MESSAGE_THREAD",
        ingested_at=NOW - timedelta(days=1),
        original_language="hi",
    )
    d3_society_notice = SourceDocument(
        id=NodeId("doc-society-notice"),
        provenance=_prov(source_document_id="doc-society-notice", region="whole-document"),
        channel="email",
        raw_payload_ref="emails/sunrise-society-aug-2026.eml",
        document_type="SOCIETY_HOA_NOTICE",
        ingested_at=NOW - timedelta(days=5),
        original_language="en",
    )
    d4_medical_reminder = SourceDocument(
        id=NodeId("doc-pharmacy-sms"),
        provenance=_prov(source_document_id="doc-pharmacy-sms", region="whole-document"),
        channel="sms",
        raw_payload_ref="sms/pharmacy-reminder-2026-08-19.txt",
        document_type="MEDICAL_DOCUMENT",
        ingested_at=NOW - timedelta(days=3),
        original_language="en",
    )
    d5_attendance_register = SourceDocument(
        id=NodeId("doc-attendance-register"),
        provenance=_prov(source_document_id="doc-attendance-register", region="whole-document"),
        channel="upload",
        raw_payload_ref="registers/maya-attendance-2026-08.jpg",
        document_type="ATTENDANCE_REGISTER",
        ingested_at=NOW - timedelta(days=1),
        original_language="hi",
    )
    nodes += [d1_receipt, d2_school_chat, d3_society_notice, d4_medical_reminder, d5_attendance_register]

    # -- persons ---------------------------------------------------------------

    priya = Person(
        id=NodeId("person-priya"),
        provenance=_prov(source_document_id="doc-school-whatsapp", region="header"),
        display_name="Priya",
        aliases=("Priya Sharma", "Mom"),
        role=PersonRole.ADULT,
        can_drive=True,
        can_sign=True,
        has_bank_access=True,
        has_medical_proxy=True,
        contact_channels=("whatsapp:+91-90000-00001",),
        language_profile=_language_profile("hi"),
    )
    aarav = Person(
        id=NodeId("person-aarav"),
        provenance=_prov(source_document_id="doc-school-whatsapp", region="header"),
        display_name="Aarav",
        aliases=("आरव", "Arav"),
        role=PersonRole.CHILD,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=_language_profile("hi"),
    )
    dadi = Person(
        id=NodeId("person-dadi"),
        provenance=_prov(source_document_id="doc-pharmacy-sms", region="recipient"),
        display_name="Dadi",
        aliases=("Grandmother",),
        role=PersonRole.ELDER,
        can_drive=False,
        can_sign=True,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=("voice:+91-90000-00003",),
        language_profile=_language_profile("hi"),
    )
    maya = Person(
        id=NodeId("person-maya"),
        provenance=_prov(source_document_id="doc-attendance-register", region="header", confidence=0.85),
        display_name="Maya",
        aliases=("Maya Bai",),
        role=PersonRole.STAFF,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=("voice:+91-90000-00004",),
        language_profile=_language_profile("hi"),
    )
    nodes += [priya, aarav, dadi, maya]

    # -- constraints -------------------------------------------------------------

    c1_nut_free = Constraint(
        id=NodeId("constraint-nut-free"),
        provenance=_prov(
            source_document_id="doc-school-whatsapp",
            region="msg-14",
            derivation=Derivation.EXTRACTED,
            confidence=0.97,
        ),
        kind=ConstraintKind.DIETARY,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={"allergen": "nut"},
        original_text="Aarav is severely allergic to nuts — no nuts in the house, ever.",
    )
    c2_nap_window = Constraint(
        id=NodeId("constraint-dadi-nap"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="msg-3",
            derivation=Derivation.INFERRED,
            confidence=0.7,
        ),
        kind=ConstraintKind.SCHEDULE,
        severity=ConstraintSeverity.SOFT,
        validity_start=None,
        validity_end=None,
        structured={"quiet_hours": "14:00-16:00"},
        original_text="Dadi naps most afternoons between 2 and 4 — best not to schedule errands then.",
    )
    nodes += [c1_nut_free, c2_nap_window]

    # -- vendors / provider ------------------------------------------------------

    v1_society = Vendor(
        id=NodeId("vendor-sunrise-society"),
        provenance=_prov(source_document_id="doc-society-notice", region="letterhead"),
        category="housing",
        contacts=("society@sunrise-apartments.example",),
        reliability_score=0.9,
        response_latency_hours=48.0,
    )
    v2_freshmart = Vendor(
        id=NodeId("vendor-freshmart"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="header"),
        category="grocery",
        contacts=("+91-80000-00002",),
        reliability_score=0.85,
        response_latency_hours=None,
    )
    pr1_pharmacy = Provider(
        id=NodeId("provider-mehta-pharmacy"),
        provenance=_prov(source_document_id="doc-pharmacy-sms", region="sender"),
        name="Mehta Pharmacy",
        category="pharmacy",
        rating=4.5,
        distance_km=1.2,
        availability_notes="open 9am-9pm",
        price_band="$$",
        specialisations=("home delivery",),
    )
    nodes += [v1_society, v2_freshmart, pr1_pharmacy]

    # -- obligations -------------------------------------------------------------

    o1_pickup = Obligation(
        id=NodeId("obligation-pickup-aarav"),
        provenance=_prov(source_document_id="doc-school-whatsapp", region="msg-9", confidence=0.95),
        title="Pick up Aarav from school",
        obligation_type="errand",
        due_at=NOW + timedelta(hours=6, minutes=30),
        must_start_by=NOW + timedelta(hours=6),
        effort_estimate_minutes=30,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )
    o2_prescription = Obligation(
        id=NodeId("obligation-renew-prescription"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="msg-1",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
        title="Renew Dadi's blood-pressure prescription",
        obligation_type="medical",
        due_at=NOW + timedelta(days=3),
        must_start_by=NOW + timedelta(days=1),
        effort_estimate_minutes=20,
        status=ObligationStatus.COMPLETED,
        stated_or_implied=ObligationDerivation.IMPLIED,
    )
    o3_maintenance_original = Obligation(
        id=NodeId("obligation-pay-maintenance"),
        provenance=_prov(source_document_id="doc-society-notice", region="due-date-line", confidence=0.93),
        title="Pay society maintenance",
        obligation_type="payment",
        due_at=NOW + timedelta(days=2),
        must_start_by=None,
        effort_estimate_minutes=10,
        status=ObligationStatus.SUPERSEDED,
        stated_or_implied=ObligationDerivation.STATED,
    )
    o3b_maintenance_extended = Obligation(
        id=NodeId("obligation-pay-maintenance-v2"),
        provenance=_prov(
            source_document_id="doc-society-notice", region="revised-due-date-line", confidence=0.93
        ),
        title="Pay society maintenance (extended deadline)",
        obligation_type="payment",
        due_at=NOW + timedelta(days=9),
        must_start_by=None,
        effort_estimate_minutes=10,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )
    o4_pharmacy_visit = Obligation(
        id=NodeId("obligation-visit-pharmacy"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="msg-2",
            derivation=Derivation.INFERRED,
            confidence=0.75,
        ),
        title="Collect prescription from pharmacy",
        obligation_type="errand",
        due_at=NOW + timedelta(hours=6),
        must_start_by=NOW + timedelta(hours=5),
        effort_estimate_minutes=25,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.IMPLIED,
    )
    o6_groceries = Obligation(
        id=NodeId("obligation-weekly-groceries"),
        provenance=_prov(
            source_document_id="doc-freshmart-receipt", region="whole-document", confidence=0.88
        ),
        title="Buy weekly groceries",
        obligation_type="errand",
        due_at=NOW - timedelta(days=2),
        must_start_by=None,
        effort_estimate_minutes=45,
        status=ObligationStatus.COMPLETED,
        stated_or_implied=ObligationDerivation.STATED,
    )
    o7_maya_salary = Obligation(
        id=NodeId("obligation-pay-maya-salary"),
        provenance=_prov(
            source_document_id="doc-attendance-register", region="whole-document", confidence=0.85
        ),
        title="Pay Maya's August salary",
        obligation_type="payment",
        due_at=NOW + timedelta(days=5),
        must_start_by=None,
        effort_estimate_minutes=5,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.IMPLIED,
    )
    nodes += [
        o1_pickup,
        o2_prescription,
        o3_maintenance_original,
        o4_pharmacy_visit,
        o6_groceries,
        o7_maya_salary,
    ]
    # o3b is NOT written directly here — it is written via `supersede_node`
    # by the loader (see `SeedResult.supersession`), so the seed dataset
    # demonstrates real supersession mechanics end-to-end.

    # -- recurring commitment / ledger events -------------------------------------

    rc1_maintenance = RecurringCommitment(
        id=NodeId("commitment-society-maintenance"),
        provenance=_prov(source_document_id="doc-society-notice", region="whole-document", confidence=0.9),
        label="Sunrise Society maintenance",
        counterparty="Sunrise Apartments Society",
        amount=2500.0,
        cadence="monthly",
        price_history=((NOW - timedelta(days=365), 2300.0), (NOW - timedelta(days=30), 2500.0)),
        last_used_at=NOW - timedelta(days=30),
        status="active",
    )
    l1_maintenance_debit = LedgerEvent(
        id=NodeId("ledger-maintenance-debit"),
        provenance=_prov(
            source_document_id="doc-society-notice", region="payment-confirmation", confidence=0.9
        ),
        kind=LedgerEventKind.DEBIT,
        amount=2500.0,
        currency="INR",
        occurred_at=NOW - timedelta(hours=3),
        counterparty_raw="SUNRISE SOCIETY MAINT",
    )
    l2_grocery_debit = LedgerEvent(
        id=NodeId("ledger-freshmart-debit"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="total-line", confidence=0.95),
        kind=LedgerEventKind.DEBIT,
        amount=850.0,
        currency="INR",
        occurred_at=NOW - timedelta(days=2),
        counterparty_raw="FRESHMART GROCERY",
    )
    l3_last_week_grocery_debit = LedgerEvent(
        id=NodeId("ledger-freshmart-debit-prior-week"),
        provenance=_prov(
            source_document_id="doc-freshmart-receipt", region="prior-week-reference", confidence=0.7
        ),
        kind=LedgerEventKind.DEBIT,
        amount=410.0,
        currency="INR",
        occurred_at=NOW - timedelta(days=9),
        counterparty_raw="FRESHMART GROCERY",
    )
    l4_maya_advance = LedgerEvent(
        id=NodeId("ledger-maya-advance"),
        provenance=_prov(source_document_id="doc-attendance-register", region="margin-note", confidence=0.8),
        kind=LedgerEventKind.ADVANCE,
        amount=2000.0,
        currency="INR",
        occurred_at=NOW - timedelta(days=10),
        counterparty_raw="MAYA BAI",
    )
    nodes += [
        rc1_maintenance,
        l1_maintenance_debit,
        l2_grocery_debit,
        l3_last_week_grocery_debit,
        l4_maya_advance,
    ]

    # -- purchase items ------------------------------------------------------------

    pi1_nut_free_bread = PurchaseItem(
        id=NodeId("item-nut-free-bread"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="line-3", confidence=0.9),
        ledger_event_id=l2_grocery_debit.id,
        description="Nut-free multigrain bread",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=90.0,
        line_total=90.0,
    )
    pi2_milk = PurchaseItem(
        id=NodeId("item-milk"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="line-1", confidence=0.9),
        ledger_event_id=l2_grocery_debit.id,
        description="Milk 1L",
        normalized_category="groceries",
        quantity=2.0,
        unit_price=60.0,
        line_total=120.0,
    )
    pi3_mixed_nuts = PurchaseItem(
        id=NodeId("item-mixed-nuts"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="line-7", confidence=0.88),
        ledger_event_id=l2_grocery_debit.id,
        description="Mixed nuts snack pack",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=140.0,
        line_total=140.0,
    )
    pi4_storebrand_paneer = PurchaseItem(
        id=NodeId("item-storebrand-paneer"),
        provenance=_prov(source_document_id="doc-freshmart-receipt", region="line-5", confidence=0.85),
        ledger_event_id=l2_grocery_debit.id,
        description="Store-brand paneer 200g",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=80.0,
        line_total=80.0,
    )
    pi5_usual_paneer = PurchaseItem(
        id=NodeId("item-usual-paneer"),
        provenance=_prov(
            source_document_id="doc-freshmart-receipt", region="prior-week-line-2", confidence=0.7
        ),
        ledger_event_id=l3_last_week_grocery_debit.id,
        description="Amul paneer 200g",
        normalized_category="groceries",
        quantity=1.0,
        unit_price=95.0,
        line_total=95.0,
    )
    nodes += [pi1_nut_free_bread, pi2_milk, pi3_mixed_nuts, pi4_storebrand_paneer, pi5_usual_paneer]

    # -- decision / branches / council positions / outcome ------------------------

    decision1 = Decision(
        id=NodeId("decision-prescription-fulfilment"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.75,
        ),
        question="Renew Dadi's prescription via home delivery or in-person pharmacy pickup?",
        trigger="Pharmacy reminder SMS 3 days before refill due",
        status=DecisionStatus.RESOLVED,
        resolution_summary="Home delivery — avoids an errand during Dadi's nap window.",
        rationale=(
            "Delivery costs slightly more but avoids scheduling conflict with "
            "obligation-visit-pharmacy and respects Dadi's afternoon rest pattern "
            "(constraint-dadi-nap)."
        ),
    )
    branch1_delivery = Branch(
        id=NodeId("branch-home-delivery"),
        provenance=_prov(source_document_id="doc-pharmacy-sms", region="whole-document", confidence=0.75),
        decision_id=decision1.id,
        label="Home delivery",
        projected_impacts={"cost": "+50 INR delivery fee", "schedule_risk": "none"},
        grounding_refs=("doc-pharmacy-sms",),
        critiques=(),
    )
    branch2_pickup = Branch(
        id=NodeId("branch-pharmacy-pickup"),
        provenance=_prov(source_document_id="doc-pharmacy-sms", region="whole-document", confidence=0.75),
        decision_id=decision1.id,
        label="In-person pharmacy pickup",
        projected_impacts={"cost": "0 INR", "schedule_risk": "conflicts with Dadi's nap window"},
        grounding_refs=("doc-pharmacy-sms",),
        critiques=("Collides with constraint-dadi-nap if scheduled 14:00-16:00",),
    )
    council_position1 = CouncilPosition(
        id=NodeId("position-favour-delivery"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.8,
        ),
        decision_id=decision1.id,
        held_by_agent=AgentId("A42"),
        stance="supports",
        branch_id=branch1_delivery.id,
        reasoning="Household schedule specialist: delivery removes a scheduling conflict at negligible cost.",
        evidence_refs=("doc-pharmacy-sms", "constraint-dadi-nap"),
    )
    council_position2 = CouncilPosition(
        id=NodeId("position-favour-pickup"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.55,
        ),
        decision_id=decision1.id,
        held_by_agent=AgentId("A44"),
        stance="opposes",
        branch_id=branch2_pickup.id,
        reasoning=(
            "Household finance specialist: pickup is free; delivery fee is an avoidable recurring cost."
        ),
        evidence_refs=("doc-pharmacy-sms",),
    )
    outcome1 = Outcome(
        id=NodeId("outcome-prescription-delivered"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.85,
        ),
        predicted="Delivered by Friday with no schedule conflict",
        actual="Delivered by Friday, no schedule conflict",
        variance=0.0,
        attribution_tags=("on-time", "no-conflict"),
    )
    nodes += [decision1, branch1_delivery, branch2_pickup, council_position1, council_position2, outcome1]

    # -- action record / approval request / pattern --------------------------------

    action_record1 = ActionRecord(
        id=NodeId("action-record-delivery-request"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.85,
        ),
        action_type="send_pharmacy_delivery_request",
        executed_at=NOW - timedelta(hours=12),
        approved_by=priya.id,
    )
    approval_request1 = ApprovalRequest(
        id=NodeId("approval-delivery-request"),
        provenance=_prov(
            source_document_id="doc-pharmacy-sms",
            region="whole-document",
            derivation=Derivation.INFERRED,
            confidence=0.85,
        ),
        proposed_action_summary=(
            "Request home delivery of Dadi's blood-pressure prescription from Mehta Pharmacy."
        ),
        evidence_bundle={
            "reasoning": "Avoids errand during Dadi's nap window; cost delta is small.",
            "decision_id": str(decision1.id),
        },
        risk_tier="R2",
        confidence=0.85,
        consequence_if_wrong="Prescription arrives a day late; no financial or safety impact.",
        status=ApprovalStatus.APPROVED,
        expires_at=NOW + timedelta(days=1),
    )
    pattern1 = Pattern(
        id=NodeId("pattern-priya-does-grocery-runs"),
        provenance=_ambiguous_prov(confidence=0.6),
        description="Grocery runs are consistently done by Priya, usually within 2 days of the prior run.",
        support_count=2,
        contributing_outcome_ids=(outcome1.id,),
    )
    attendance1_maya_august = AttendanceRecord(
        id=NodeId("attendance-maya-2026-08"),
        provenance=_prov(
            source_document_id="doc-attendance-register",
            region="whole-document",
            derivation=Derivation.EXTRACTED,
            confidence=0.8,
        ),
        staff_person_id=maya.id,
        month="2026-08",
        days_present=22,
        days_absent=2,
        days_on_leave=1,
        total_days_in_period=25,
        daily_marks={
            "01": "present",
            "02": "present",
            "03": "absent",
            "04": "present",
            "05": "leave",
            "06": "present",
            "07": "present",
        },
        # Cross-reference-only text (ADR-013) — the real advance amount
        # lives on `ledger-maya-advance` (LEDGER_EVENT, kind=ADVANCE),
        # never parsed back out of this margin note.
        advance_notations=("₹2,000 advance noted in margin, 12 Aug",),
    )
    valuation1_priya = ValuationProfile(
        id=NodeId("valuation-priya"),
        provenance=_prov(
            source_document_id="doc-school-whatsapp",
            region="derived",
            derivation=Derivation.INFERRED,
            confidence=0.7,
        ),
        person_id=priya.id,
        # A real, sparse cardinal cost matrix (ADR-014) over three real
        # seeded OBLIGATIONs — o2 (renew prescription) never appears here,
        # matching `ValuationProfile.costs`'s own contract: a task absent
        # from this dict means Priya was never asked about it, never a
        # fabricated `0.0`.
        costs={
            str(o1_pickup.id): 3.0,
            str(o6_groceries.id): 1.0,
            str(o7_maya_salary.id): 5.0,
        },
        elicitation_method="mixed",
    )
    nodes += [action_record1, approval_request1, pattern1, attendance1_maya_august, valuation1_priya]

    # -- edges -----------------------------------------------------------------

    def _edge(
        edge_id: str, edge_type: EdgeType, from_id: NodeId, to_id: NodeId, *, confidence: float = 0.9
    ) -> Edge:
        return Edge(
            id=EdgeId(edge_id),
            provenance=_prov(
                source_document_id="doc-school-whatsapp", region="derived", confidence=confidence
            ),
            edge_type=edge_type,
            from_id=from_id,
            to_id=to_id,
        )

    edges += [
        _edge("e-states-pickup", EdgeType.STATES, d2_school_chat.id, o1_pickup.id),
        _edge("e-implies-prescription", EdgeType.IMPLIES, d4_medical_reminder.id, o2_prescription.id),
        _edge("e-states-maintenance", EdgeType.STATES, d3_society_notice.id, o3_maintenance_original.id),
        _edge("e-owned-o1", EdgeType.OWNED_BY, o1_pickup.id, priya.id),
        _edge("e-owned-o2", EdgeType.OWNED_BY, o2_prescription.id, priya.id),
        _edge("e-owned-o3", EdgeType.OWNED_BY, o3_maintenance_original.id, priya.id),
        _edge("e-owned-o4", EdgeType.OWNED_BY, o4_pharmacy_visit.id, priya.id),
        _edge("e-owned-o6", EdgeType.OWNED_BY, o6_groceries.id, priya.id),
        _edge("e-benefits-o1", EdgeType.BENEFITS, o1_pickup.id, aarav.id),
        _edge("e-benefits-o2", EdgeType.BENEFITS, o2_prescription.id, dadi.id),
        _edge("e-conflicts-o1-o4", EdgeType.CONFLICTS_WITH, o1_pickup.id, o4_pharmacy_visit.id),
        _edge("e-violates-o4-c2", EdgeType.VIOLATES, o4_pharmacy_visit.id, c2_nap_window.id),
        _edge("e-depends-o4-o2", EdgeType.DEPENDS_ON, o4_pharmacy_visit.id, o2_prescription.id),
        _edge("e-completes-o2-outcome1", EdgeType.COMPLETES_INTO, o2_prescription.id, outcome1.id),
        _edge("e-belongs-l1-rc1", EdgeType.BELONGS_TO, l1_maintenance_debit.id, rc1_maintenance.id),
        _edge("e-owed-l1-v1", EdgeType.OWED_TO, l1_maintenance_debit.id, v1_society.id),
        _edge("e-owed-l2-v2", EdgeType.OWED_TO, l2_grocery_debit.id, v2_freshmart.id),
        _edge("e-owed-l3-v2", EdgeType.OWED_TO, l3_last_week_grocery_debit.id, v2_freshmart.id),
        _edge("e-contains-d1-b1", EdgeType.CONTAINS, decision1.id, branch1_delivery.id),
        _edge("e-contains-d1-b2", EdgeType.CONTAINS, decision1.id, branch2_pickup.id),
        _edge("e-supports-p1-b1", EdgeType.SUPPORTS, council_position1.id, branch1_delivery.id),
        _edge("e-opposes-p2-b2", EdgeType.OPPOSES, council_position2.id, branch2_pickup.id),
        _edge("e-grounded-b1-d1doc", EdgeType.GROUNDED_IN, branch1_delivery.id, d1_receipt.id),
        _edge("e-grounded-p1-d4", EdgeType.GROUNDED_IN, council_position1.id, d4_medical_reminder.id),
        _edge("e-resolved-d1-b1", EdgeType.RESOLVED_AS, decision1.id, branch1_delivery.id),
        _edge("e-conceded-d1-priya", EdgeType.CONCEDED_BY, decision1.id, priya.id),
        _edge("e-predicted-outcome1-b1", EdgeType.PREDICTED_BY, outcome1.id, branch1_delivery.id),
        _edge("e-constrains-c1-aarav", EdgeType.CONSTRAINS, c1_nut_free.id, aarav.id),
        _edge("e-constrains-c2-dadi", EdgeType.CONSTRAINS, c2_nap_window.id, dadi.id),
        _edge("e-booked-o4-pr1", EdgeType.BOOKED_WITH, o4_pharmacy_visit.id, pr1_pharmacy.id),
        _edge("e-learned-pattern1-outcome1", EdgeType.LEARNED_FROM, pattern1.id, outcome1.id),
        # ADR-012 (Phase 5, DEBT-002's repayment): the three edges every
        # real ApprovalGate.approve_and_execute call writes atomically
        # alongside an ActionRecord. action_record1/approval_request1 are
        # seed-data stand-ins for that same real flow, so they carry the
        # same edges a live run would have produced -- not because seed
        # data is special-cased, but because this is what "correctly
        # written" now means for these two node types (see
        # app.graph.integrity_checker's updated docstring).
        _edge("e-acts_on-action1-o4", EdgeType.ACTS_ON, action_record1.id, o4_pharmacy_visit.id),
        _edge("e-authorizes-approval1-action1", EdgeType.AUTHORIZES, approval_request1.id, action_record1.id),
        _edge("e-approved_by-approval1-priya", EdgeType.APPROVED_BY, approval_request1.id, priya.id),
        _edge("e-lineitem-pi1-l2", EdgeType.LINE_ITEM_OF, pi1_nut_free_bread.id, l2_grocery_debit.id),
        _edge("e-lineitem-pi2-l2", EdgeType.LINE_ITEM_OF, pi2_milk.id, l2_grocery_debit.id),
        _edge("e-lineitem-pi3-l2", EdgeType.LINE_ITEM_OF, pi3_mixed_nuts.id, l2_grocery_debit.id),
        _edge("e-lineitem-pi4-l2", EdgeType.LINE_ITEM_OF, pi4_storebrand_paneer.id, l2_grocery_debit.id),
        _edge("e-lineitem-pi5-l3", EdgeType.LINE_ITEM_OF, pi5_usual_paneer.id, l3_last_week_grocery_debit.id),
        _edge("e-discharges-l2-o6", EdgeType.DISCHARGES, l2_grocery_debit.id, o6_groceries.id),
        _edge("e-verifies-pi1-c1", EdgeType.VERIFIES, pi1_nut_free_bread.id, c1_nut_free.id, confidence=0.97),
        _edge(
            "e-contradicts-pi3-c1", EdgeType.CONTRADICTS, pi3_mixed_nuts.id, c1_nut_free.id, confidence=0.9
        ),
        _edge(
            "e-absent-c2-missing-doc",
            EdgeType.ABSENT_FROM,
            c2_nap_window.id,
            NodeId("doc-expected-caregiver-log-never-arrived"),
        ),
        _edge("e-substitutes-pi4-pi5", EdgeType.SUBSTITUTES, pi4_storebrand_paneer.id, pi5_usual_paneer.id),
        _edge("e-effort-pi1-priya", EdgeType.EVIDENCES_EFFORT, pi1_nut_free_bread.id, priya.id),
        _edge("e-effort-l1-priya", EdgeType.EVIDENCES_EFFORT, l1_maintenance_debit.id, priya.id),
        # These two reference obligation-pay-maintenance-v2 (o3b), which is
        # written via `supersede_node` *after* the initial node batch — see
        # `SeedResult.supersession` and `seed_loader.load_demo_household`.
        # Writing edges after the node they reference exists is required
        # (the integrity checker would otherwise see a dangling edge).
        _edge(
            "e-supersedes-o3b-o3",
            EdgeType.SUPERSEDES,
            o3b_maintenance_extended.id,
            o3_maintenance_original.id,
        ),
        _edge("e-owned-o3b", EdgeType.OWNED_BY, o3b_maintenance_extended.id, priya.id),
        _edge("e-paidfor-l1-o3b", EdgeType.PAID_FOR, l1_maintenance_debit.id, o3b_maintenance_extended.id),
        # ADR-013 (Phase 7, DEBT-004's repayment): the real advance amount
        # lives on this LEDGER_EVENT (never parsed from
        # attendance1_maya_august.advance_notations); `owed_to` is the
        # existing LEDGER_EVENT -> PERSON counterparty edge (gharos-graph-
        # model skill's edge table), reused here rather than inventing a
        # new edge type for "advance paid to."
        _edge("e-owed-l4-maya", EdgeType.OWED_TO, l4_maya_advance.id, maya.id),
        _edge(
            "e-attendance_of-attendance1-maya", EdgeType.ATTENDANCE_OF, attendance1_maya_august.id, maya.id
        ),
        # ADR-014 (Phase 8): whose cardinal cost matrix this is.
        _edge("e-valuation_of-valuation1-priya", EdgeType.VALUATION_OF, valuation1_priya.id, priya.id),
        # Spec §10.3D "Salary cycles -> monthly payment OBLIGATIONs" — also
        # gives doc-attendance-register (d5) a real incident edge, since
        # SOURCE_DOCUMENT has no direct edge type to ATTENDANCE_RECORD
        # (only `attendance_of`, ATTENDANCE_RECORD -> PERSON, per ADR-013).
        _edge("e-implies-o7-attendance-doc", EdgeType.IMPLIES, d5_attendance_register.id, o7_maya_salary.id),
        _edge("e-owned-o7", EdgeType.OWNED_BY, o7_maya_salary.id, priya.id),
        _edge("e-benefits-o7-maya", EdgeType.BENEFITS, o7_maya_salary.id, maya.id),
    ]

    return SeedResult(
        nodes=tuple(nodes),
        edges=tuple(edges),
        supersession=(o3_maintenance_original.id, o3b_maintenance_extended),
    )
