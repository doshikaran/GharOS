"""Behavioural tests for the narrow, Firestore-backed repositories —
`FirestorePersonRepository`, `FirestoreObligationRepository`,
`FirestoreDecisionRepository`, `FirestorePatternRepository` — exercised
against the seeded demo household.
"""

from __future__ import annotations

import pytest
from contracts.errors import ProvenanceMissing
from contracts.graph_types import Derivation, NodeId, Pattern

from app.graph.decision_repository import FirestoreDecisionRepository
from app.graph.obligation_repository import FirestoreObligationRepository
from app.graph.pattern_repository import FirestorePatternRepository
from app.graph.person_repository import FirestorePersonRepository
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import SeedResult
from tests.conftest import make_provenance


class TestFirestorePersonRepository:
    def test_get(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        repo = FirestorePersonRepository(store)
        person = repo.get(NodeId("person-priya"))
        assert person is not None
        assert person.display_name == "Priya"
        assert repo.get(NodeId("obligation-pickup-aarav")) is None  # wrong node type

    def test_find_by_alias(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        repo = FirestorePersonRepository(store)
        found = repo.find_by_alias("Priya Sharma")
        assert len(found) == 1
        assert found[0].id == NodeId("person-priya")
        assert repo.find_by_alias("priya sharma") == found  # case-insensitive
        assert repo.find_by_alias("nobody") == ()

    def test_find_by_alias_matches_display_name_too(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        repo = FirestorePersonRepository(store)
        found = repo.find_by_alias("Aarav")
        assert {p.id for p in found} == {NodeId("person-aarav")}


class TestFirestoreObligationRepository:
    def test_get(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        repo = FirestoreObligationRepository(store)
        assert repo.get(NodeId("obligation-pickup-aarav")) is not None
        assert repo.get(NodeId("person-priya")) is None

    def test_open_obligations_for_excludes_closed_statuses(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        repo = FirestoreObligationRepository(store)
        open_for_priya = {o.id for o in repo.open_obligations_for(NodeId("person-priya"))}
        # obligation-renew-prescription is COMPLETED, obligation-pay-maintenance
        # is SUPERSEDED, obligation-weekly-groceries is COMPLETED — all excluded
        assert NodeId("obligation-pickup-aarav") in open_for_priya
        assert NodeId("obligation-visit-pharmacy") in open_for_priya
        assert NodeId("obligation-pay-maintenance-v2") in open_for_priya
        assert NodeId("obligation-renew-prescription") not in open_for_priya
        assert NodeId("obligation-pay-maintenance") not in open_for_priya
        assert NodeId("obligation-weekly-groceries") not in open_for_priya

    def test_unassigned_returns_empty_when_every_obligation_is_owned(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        repo = FirestoreObligationRepository(store)
        # every obligation in the seed dataset has an owned_by edge
        assert repo.unassigned() == ()


class TestFirestoreDecisionRepository:
    def test_get_decision(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        repo = FirestoreDecisionRepository(store)
        decision = repo.get_decision(NodeId("decision-prescription-fulfilment"))
        assert decision is not None
        assert decision.question.startswith("Renew Dadi's prescription")

    def test_branches_and_positions_for(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        repo = FirestoreDecisionRepository(store)
        branches = repo.branches_for(NodeId("decision-prescription-fulfilment"))
        assert {b.id for b in branches} == {
            NodeId("branch-home-delivery"),
            NodeId("branch-pharmacy-pickup"),
        }
        positions = repo.positions_for(NodeId("decision-prescription-fulfilment"))
        assert {p.id for p in positions} == {
            NodeId("position-favour-delivery"),
            NodeId("position-favour-pickup"),
        }

    def test_unknown_decision_returns_none_and_empty(
        self, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        repo = FirestoreDecisionRepository(store)
        assert repo.get_decision(NodeId("decision-does-not-exist")) is None
        assert repo.branches_for(NodeId("decision-does-not-exist")) == ()
        assert repo.positions_for(NodeId("decision-does-not-exist")) == ()


class TestFirestorePatternRepository:
    def test_write_and_read_pattern(self, store: FirestoreGraphStore) -> None:
        repo = FirestorePatternRepository(store)
        assert repo.all_patterns() == ()
        pattern = Pattern(
            id=NodeId("pattern-1"),
            provenance=make_provenance(derivation=Derivation.INFERRED, confidence=0.6),
            description="Dad's appointments slip on Mondays",
            support_count=4,
            contributing_outcome_ids=(NodeId("outcome-1"),),
        )
        written_id = repo.write_pattern(pattern)
        assert written_id == NodeId("pattern-1")
        assert repo.all_patterns() == (pattern,)

    def test_write_pattern_rejects_missing_provenance(self, store: FirestoreGraphStore) -> None:
        repo = FirestorePatternRepository(store)
        bad_pattern = Pattern.__new__(Pattern)  # bypass __init__, no provenance set
        with pytest.raises((ProvenanceMissing, AttributeError)):
            repo.write_pattern(bad_pattern)
