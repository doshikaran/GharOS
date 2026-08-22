"""All 14 traversal operations (spec §5.7), each proven against the
seeded demo household (`seeds.demo_household`) — a non-trivial graph (36
nodes, 46+ edges, multiple hops, a real supersession, conflicting
obligations, a resolved Decision with two Branches and two
CouncilPositions) rather than a 2-node happy path, per Gate 1 and the E1
charter's explicit instruction.
"""

from __future__ import annotations

from datetime import timedelta

from contracts.graph_types import (
    Constraint,
    Decision,
    EdgeType,
    LedgerEvent,
    NodeId,
    Obligation,
    Outcome,
    Person,
    PurchaseItem,
)

from app.graph.reader import FirestoreGraphReader
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import NOW, SeedResult

PRIYA = NodeId("person-priya")
AARAV = NodeId("person-aarav")
DADI = NodeId("person-dadi")


class TestNeighbours:
    def test_bidirectional_by_edge_type(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        owned = reader.neighbours(PRIYA, EdgeType.OWNED_BY)
        titles = {n.title for n in owned if isinstance(n, Obligation)}
        assert titles == {
            "Pick up Aarav from school",
            "Renew Dadi's blood-pressure prescription",
            "Pay society maintenance",
            "Pay society maintenance (extended deadline)",
            "Collect prescription from pharmacy",
            "Buy weekly groceries",
        }

    def test_from_the_other_endpoint_returns_the_same_relationship(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        owners = reader.neighbours(NodeId("obligation-pickup-aarav"), EdgeType.OWNED_BY)
        assert len(owners) == 1
        assert isinstance(owners[0], Person)
        assert owners[0].id == PRIYA

    def test_unknown_node_returns_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.neighbours(NodeId("does-not-exist"), EdgeType.OWNED_BY) == ()


class TestPath:
    def test_directed_shortest_path(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        chain = reader.path(NodeId("doc-school-whatsapp"), PRIYA)
        assert [e.edge_type for e in chain] == [EdgeType.STATES, EdgeType.OWNED_BY]

    def test_no_path_returns_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.path(AARAV, NodeId("vendor-freshmart")) == ()

    def test_same_node_returns_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.path(PRIYA, PRIYA) == ()


class TestBlastRadius:
    def test_depth_zero_is_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.blast_radius(NodeId("obligation-pickup-aarav"), depth=0) == ()

    def test_depth_one_reaches_direct_neighbours(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        reached = reader.blast_radius(NodeId("obligation-pickup-aarav"), depth=1)
        ids = {n.id for n in reached}  # type: ignore[attr-defined]
        assert PRIYA in ids
        assert AARAV in ids
        assert NodeId("doc-school-whatsapp") in ids
        assert NodeId("obligation-visit-pharmacy") in ids  # via conflicts_with

    def test_deeper_radius_reaches_further_and_grows_monotonically(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        shallow = reader.blast_radius(NodeId("obligation-pickup-aarav"), depth=1)
        deep = reader.blast_radius(NodeId("obligation-pickup-aarav"), depth=3)
        assert len(deep) >= len(shallow)
        deep_ids = {n.id for n in deep}  # type: ignore[attr-defined]
        # 3 hops from the pickup obligation reaches the pharmacy provider
        # via conflicts_with -> obligation-visit-pharmacy -> booked_with
        assert NodeId("provider-mehta-pharmacy") in deep_ids


class TestConflicts:
    def test_returns_conflicts_with_and_violates_unresolved(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        conflicts = reader.conflicts(scope="all")
        types = {e.edge_type for e in conflicts}
        assert types == {EdgeType.CONFLICTS_WITH, EdgeType.VIOLATES}
        assert all(e.provenance.superseded_at is None for e in conflicts)

    def test_scoped_to_a_single_node(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        scoped = reader.conflicts(scope=str(NodeId("obligation-visit-pharmacy")))
        assert len(scoped) == 2  # conflicts_with O1, violates C2
        untouched = reader.conflicts(scope=str(PRIYA))
        assert untouched == ()


class TestLoad:
    def test_sums_effort_minutes_in_window(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        window = (NOW - timedelta(hours=1), NOW + timedelta(days=1))
        # within this window: pickup (30) + visit-pharmacy (25) = 55
        assert reader.load(PRIYA, window) == 55.0

    def test_empty_window_returns_zero(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        window = (NOW - timedelta(days=100), NOW - timedelta(days=90))
        assert reader.load(PRIYA, window) == 0.0


class TestSeries:
    def test_all_ledger_events_belonging_to_a_commitment(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        events = reader.series(NodeId("commitment-society-maintenance"))
        assert len(events) == 1
        assert isinstance(events[0], LedgerEvent)
        assert events[0].id == NodeId("ledger-maintenance-debit")

    def test_unknown_commitment_returns_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.series(NodeId("commitment-does-not-exist")) == ()


class TestHistory:
    def test_outcomes_for_an_obligation(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        outcomes = reader.history(NodeId("obligation-renew-prescription"))
        assert len(outcomes) == 1
        assert isinstance(outcomes[0], Outcome)
        assert outcomes[0].id == NodeId("outcome-prescription-delivered")

    def test_no_outcomes_returns_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.history(NodeId("obligation-pickup-aarav")) == ()


class TestDecisionsTouching:
    def test_direct_and_indirect_via_branch_and_position(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        decisions = reader.decisions_touching(PRIYA)
        assert {d.id for d in decisions} == {NodeId("decision-prescription-fulfilment")}

    def test_via_branch(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        decisions = reader.decisions_touching(NodeId("branch-home-delivery"))
        assert {d.id for d in decisions} == {NodeId("decision-prescription-fulfilment")}

    def test_unrelated_entity_returns_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.decisions_touching(NodeId("vendor-freshmart")) == ()


class TestConcessionLedger:
    def test_person_with_concessions(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        decisions = reader.concession_ledger(PRIYA)
        assert len(decisions) == 1
        assert isinstance(decisions[0], Decision)

    def test_person_with_no_concessions(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.concession_ledger(DADI) == ()


class TestUnexplained:
    def test_empty_on_seeded_graph(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.unexplained(scope="all") == ()

    def test_scoped_to_a_single_clean_node_is_empty(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        assert reader.unexplained(scope=str(PRIYA)) == ()

    def test_detects_a_directly_injected_provenance_less_node(
        self, reader: FirestoreGraphReader, seeded: SeedResult, store: FirestoreGraphStore
    ) -> None:
        """`unexplained` re-validates every stored node independently of
        the write guard — simulate corrupted/legacy data that bypassed
        `FirestoreGraphWriter` entirely (writing straight to the Firestore
        client) and confirm it is caught."""
        store._client.collection("persons").document("corrupted-1").set(  # noqa: SLF001
            {
                "id": "corrupted-1",
                "display_name": "No Provenance",
                "aliases": [],
                "role": "adult",
                "can_drive": False,
                "can_sign": False,
                "has_bank_access": False,
                "has_medical_proxy": False,
                "contact_channels": [],
                "language_profile": {
                    "primary_language": "en",
                    "languages_understood": ["en"],
                    "script_preference": "latin",
                    "code_mixing_profile": None,
                    "formality_preference": None,
                    "literacy_mode": "both",
                },
                "voiceprint_ref": None,
                "pronunciation_hints": None,
                "provenance": None,
                "_version_seq": 1,
            }
        )
        store._client.collection("node_index").document("corrupted-1").set(  # noqa: SLF001
            {"collection": "persons"}
        )
        bad = reader.unexplained(scope="all")
        assert NodeId("corrupted-1") in bad


class TestUnverified:
    def test_verified_obligation_excluded_unverified_included(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        unverified = reader.unverified(scope="all")
        assert NodeId("obligation-weekly-groceries") not in unverified  # has a discharges edge
        assert NodeId("obligation-pickup-aarav") in unverified  # no verification edge at all

    def test_scoped_to_a_single_unverified_node(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        scoped = reader.unverified(scope=str(NodeId("obligation-pickup-aarav")))
        assert scoped == (NodeId("obligation-pickup-aarav"),)

    def test_scoped_to_a_single_verified_node_returns_empty(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        scoped = reader.unverified(scope=str(NodeId("obligation-weekly-groceries")))
        assert scoped == ()

    def test_constraint_with_verifies_edge_excluded(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        unverified = reader.unverified(scope="all")
        assert NodeId("constraint-nut-free") not in unverified  # verifies + contradicts
        assert NodeId("constraint-dadi-nap") in unverified  # only violates/constrains/absent_from


class TestExpectedButAbsent:
    def test_returns_the_never_arrived_source_document_id(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        absent = reader.expected_but_absent(NodeId("constraint-dadi-nap"))
        assert absent == (NodeId("doc-expected-caregiver-log-never-arrived"),)

    def test_constraint_with_no_absent_from_edge_returns_empty(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        assert reader.expected_but_absent(NodeId("constraint-nut-free")) == ()


class TestSpendByCategory:
    def test_sums_line_totals_by_category_in_window(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        window = (NOW - timedelta(days=15), NOW + timedelta(days=1))
        totals = reader.spend_by_category(window)
        assert totals == {"groceries": 90.0 + 120.0 + 140.0 + 80.0 + 95.0}

    def test_narrow_window_excludes_older_purchases(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        window = (NOW - timedelta(hours=1), NOW + timedelta(days=1))
        totals = reader.spend_by_category(window)
        assert totals == {}


class TestEffortEvidence:
    def test_purchase_item_sourced_effort_within_window(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        window = (NOW - timedelta(days=15), NOW + timedelta(days=1))
        items = reader.effort_evidence(PRIYA, window)
        assert len(items) == 1
        assert isinstance(items[0], PurchaseItem)
        assert items[0].id == NodeId("item-nut-free-bread")

    def test_ledger_event_sourced_effort_is_excluded_by_return_type(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        """`ledger-maintenance-debit` also has an `evidences_effort` edge
        to Priya, but the protocol's return type is `tuple[PurchaseItem,
        ...]` — a LEDGER_EVENT-sourced edge has nothing to return there."""
        window = (NOW - timedelta(days=15), NOW + timedelta(days=1))
        items = reader.effort_evidence(PRIYA, window)
        assert all(isinstance(i, PurchaseItem) for i in items)

    def test_person_with_no_effort_evidence(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        window = (NOW - timedelta(days=15), NOW + timedelta(days=1))
        assert reader.effort_evidence(AARAV, window) == ()


def test_get_node_returns_typed_instances_for_every_scope_touched(
    reader: FirestoreGraphReader, seeded: SeedResult
) -> None:
    assert isinstance(reader.get_node(PRIYA), Person)
    assert isinstance(reader.get_node(NodeId("obligation-pickup-aarav")), Obligation)
    assert isinstance(reader.get_node(NodeId("constraint-nut-free")), Constraint)
    assert reader.get_node(NodeId("does-not-exist")) is None
