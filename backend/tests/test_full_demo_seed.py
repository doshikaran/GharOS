"""The full 4-minute-demo seed (`seeds.full_demo` / `seeds.seed_loader.
load_full_demo`) — PHASES.md Phase 15 (E1).

Proves the aggregated demo graph loads clean through the real
provenance-guarded writer (`unexplained` empty, integrity checker clean,
all 18 node types) and that every §24 demo beat has the exact graph
shape it needs to land live:

* the field-trip email -> >= 5 implied obligations;
* the temporal collision (Ananya 1:30 pickup vs Priya 1:00 meeting);
* the nut-allergy vs Tuesday canteen-menu hard conflict;
* the money leak (silent hike + unused service + duplicate charge);
* >= 3 settled OUTCOMEs for each calibration category the panel shows,
  relocation honestly left at zero;
* the engineered verification receipt (discharges + substitutes +
  absent_from on the nut-free item);
* the Household Council car decision as a walkable record.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    AttendanceRecord,
    Branch,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    CouncilPosition,
    Decision,
    DecisionStatus,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    Person,
    PersonRole,
    RecurringCommitment,
    SourceDocument,
)

from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.collections import NODE_TYPE_TO_COLLECTION
from app.persistence.firestore_store import FirestoreGraphStore
from app.solvers.calibration_stats import compute_calibration
from seeds.full_demo import build_full_demo
from seeds.seed_loader import load_full_demo

_NOW = datetime(2026, 8, 22, 9, 0, tzinfo=UTC)


@pytest.fixture
def full_seeded(writer: FirestoreGraphWriter, store: FirestoreGraphStore) -> FirestoreGraphStore:
    load_full_demo(writer)
    return store


# --------------------------------------------------------------------------
# builder purity + structural integrity
# --------------------------------------------------------------------------


def test_build_full_demo_is_pure_and_id_unique() -> None:
    from seeds.demo_household import build_demo_household

    first = build_full_demo()
    second = build_full_demo()
    # build_full_demo raises on any id collision; reaching here means unique.
    assert [str(n.id) for n in first.nodes] == [str(n.id) for n in second.nodes]  # type: ignore[attr-defined]
    assert [str(e.id) for e in first.edges] == [str(e.id) for e in second.edges]
    assert len(first.nodes) > len(build_demo_household().nodes)


def test_unexplained_is_empty(full_seeded: FirestoreGraphStore) -> None:
    assert FirestoreGraphReader(full_seeded).unexplained("all") == ()


def test_integrity_checker_is_clean(full_seeded: FirestoreGraphStore) -> None:
    violations = FirestoreGraphIntegrityChecker(full_seeded).check("all")
    assert violations == (), violations


def test_covers_all_eighteen_node_types(full_seeded: FirestoreGraphStore) -> None:
    present = {type(n) for n in full_seeded.all_current_nodes()}
    assert present == set(NODE_TYPE_TO_COLLECTION.keys())


def test_spec_26_roster_is_complete(full_seeded: FirestoreGraphStore) -> None:
    people = full_seeded.all_current_nodes((Person,))
    roles = sorted(p.role for p in people)
    assert roles.count(PersonRole.ADULT) >= 2
    assert roles.count(PersonRole.CHILD) >= 2
    assert roles.count(PersonRole.ELDER) >= 1
    assert roles.count(PersonRole.STAFF) >= 2


def test_the_four_new_hard_constraints_are_present(full_seeded: FirestoreGraphStore) -> None:
    hard = {
        c.kind for c in full_seeded.all_current_nodes((Constraint,)) if c.severity is ConstraintSeverity.HARD
    }
    # base nut-free (dietary) + the roster segment's four
    assert {
        ConstraintKind.DIETARY,
        ConstraintKind.MOBILITY,
        ConstraintKind.MEDICAL,
        ConstraintKind.EDUCATION,
        ConstraintKind.SCHEDULE,
    }.issubset(hard)


def test_at_least_twelve_ugly_documents(full_seeded: FirestoreGraphStore) -> None:
    docs = full_seeded.all_current_nodes((SourceDocument,))
    assert len(docs) >= 12
    types = {d.document_type for d in docs}
    for expected in (
        "school_communication",
        "society_notice",
        "attendance_register",
        "medical_document",
        "permission_slip",
        "utility_bill",
        "warranty",
        "upi_sms_alert",
        "receipt",
        "quote_estimate",
        "bank_statement",
    ):
        assert expected in types, expected


# --------------------------------------------------------------------------
# §24 demo beats
# --------------------------------------------------------------------------


def test_field_trip_email_yields_five_implied_obligations(full_seeded: FirestoreGraphStore) -> None:
    out = full_seeded.edges_from(NodeId("doc-fieldtrip-email"))
    implied = [e for e in out if e.edge_type is EdgeType.IMPLIES]
    stated = [e for e in out if e.edge_type is EdgeType.STATES]
    assert len(implied) >= 5
    assert len(stated) >= 1
    for e in implied:
        obl = full_seeded.get_node(e.to_id)
        assert isinstance(obl, Obligation)
        assert obl.stated_or_implied is ObligationDerivation.IMPLIED


def test_temporal_collision_is_a_live_conflict(full_seeded: FirestoreGraphStore) -> None:
    conflicts = FirestoreGraphReader(full_seeded).conflicts("all")
    pairs = {(str(e.from_id), str(e.to_id)) for e in conflicts if e.edge_type is EdgeType.CONFLICTS_WITH}
    assert ("obligation-fd-pickup-ananya", "obligation-fd-priya-meeting") in pairs


def test_nut_allergy_vs_tuesday_menu_is_a_hard_conflict(full_seeded: FirestoreGraphStore) -> None:
    conflicts = FirestoreGraphReader(full_seeded).conflicts("all")
    onto_nut_free = [
        e
        for e in conflicts
        if str(e.to_id) == "constraint-nut-free" and str(e.from_id) == "obligation-fd-canteen-tuesday-lunch"
    ]
    kinds = {e.edge_type for e in onto_nut_free}
    assert EdgeType.VIOLATES in kinds
    assert EdgeType.CONFLICTS_WITH in kinds
    nut_free = full_seeded.get_node(NodeId("constraint-nut-free"))
    assert isinstance(nut_free, Constraint)
    assert nut_free.severity is ConstraintSeverity.HARD


def test_the_money_leak_has_all_three_forms(full_seeded: FirestoreGraphStore) -> None:
    # silent price hike
    broadband = full_seeded.get_node(NodeId("commitment-fd-broadband"))
    assert isinstance(broadband, RecurringCommitment)
    amounts = [amount for _, amount in broadband.price_history]
    assert amounts == sorted(amounts) and amounts[0] < amounts[-1]

    # unused recurring service
    streaming = full_seeded.get_node(NodeId("commitment-fd-streaming"))
    assert isinstance(streaming, RecurringCommitment)
    assert streaming.status == "active"
    assert streaming.last_used_at is not None
    assert (_NOW - streaming.last_used_at).days >= 90

    # duplicate charge
    from contracts.graph_types import LedgerEvent

    d1 = full_seeded.get_node(NodeId("ledger-fd-grocery-dup-1"))
    d2 = full_seeded.get_node(NodeId("ledger-fd-grocery-dup-2"))
    assert isinstance(d1, LedgerEvent) and isinstance(d2, LedgerEvent)
    assert d1.amount == d2.amount
    assert d1.occurred_at == d2.occurred_at
    assert d1.counterparty_raw == d2.counterparty_raw


def test_calibration_categories_clear_the_threshold_relocation_stays_thin(
    full_seeded: FirestoreGraphStore,
) -> None:
    reader = FirestoreGraphReader(full_seeded)
    for tag in ("school_transition", "staff_transition", "major_purchase"):
        estimate = compute_calibration(tag, reader.outcome_variance(tag))
        assert estimate.sample_size >= 3, tag
        assert estimate.is_thin_history is False, tag
        assert estimate.mean_variance is not None

    relocation = compute_calibration("relocation", reader.outcome_variance("relocation"))
    assert relocation.sample_size == 0
    assert relocation.is_thin_history is True
    assert relocation.mean_variance is None


def test_verification_receipt_closes_the_loop_three_ways(full_seeded: FirestoreGraphStore) -> None:
    reader = FirestoreGraphReader(full_seeded)

    # (a) discharges an open shopping obligation
    discharges = full_seeded.edges_from(NodeId("ledger-fd-verification-receipt"), EdgeType.DISCHARGES)
    assert [str(e.to_id) for e in discharges] == ["obligation-fd-weekend-shop"]
    shop = full_seeded.get_node(NodeId("obligation-fd-weekend-shop"))
    assert isinstance(shop, Obligation)

    # (b) a substitution against the planned list
    subs = full_seeded.edges_from(NodeId("item-fd-vr-storebrand-paneer"), EdgeType.SUBSTITUTES)
    assert [str(e.to_id) for e in subs] == ["item-fd-vr-planned-amul-paneer"]

    # (c) the nut-free item never appeared on the receipt
    absent = reader.expected_but_absent(NodeId("constraint-nut-free"))
    assert NodeId("doc-verification-receipt") in absent


def test_household_council_car_decision_is_a_walkable_record(full_seeded: FirestoreGraphStore) -> None:
    reader = FirestoreGraphReader(full_seeded)
    decision = full_seeded.get_node(NodeId("decision-fd-car-purchase"))
    assert isinstance(decision, Decision)
    assert decision.status is DecisionStatus.RESOLVED

    branches = full_seeded.edges_from(NodeId("decision-fd-car-purchase"), EdgeType.CONTAINS)
    assert len(branches) == 4
    for e in branches:
        assert isinstance(full_seeded.get_node(e.to_id), Branch)

    positions = full_seeded.all_current_nodes((CouncilPosition,))
    car_positions = [p for p in positions if str(p.decision_id) == "decision-fd-car-purchase"]
    assert len(car_positions) >= 5
    assert len({p.held_by_agent for p in car_positions}) >= 4

    resolved = full_seeded.edges_from(NodeId("decision-fd-car-purchase"), EdgeType.RESOLVED_AS)
    assert [str(e.to_id) for e in resolved] == ["branch-fd-keep-and-cabs"]

    conceded = reader.concession_ledger(NodeId("person-rohan"))
    assert any(str(d.id) == "decision-fd-car-purchase" for d in conceded)


def test_second_staff_attendance_record_through_the_seed(full_seeded: FirestoreGraphStore) -> None:
    record = full_seeded.get_node(NodeId("attendance-salim-2026-08"))
    assert isinstance(record, AttendanceRecord)
    assert record.month == "2026-08"
    attendance_of = full_seeded.edges_from(NodeId("attendance-salim-2026-08"), EdgeType.ATTENDANCE_OF)
    assert [str(e.to_id) for e in attendance_of] == ["person-salim"]


def test_warranty_covers_edge_is_present(full_seeded: FirestoreGraphStore) -> None:
    covers = full_seeded.edges_from(NodeId("obligation-fd-purifier-warranty-claim"), EdgeType.COVERS)
    assert [str(e.to_id) for e in covers] == ["item-fd-water-purifier"]
