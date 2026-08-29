"""ADR-019 Decision 5 — verification, not new code.

The bet: `FirestoreGraphWriter.write_node`/`write_edge` are already fully
generic (confirmed Phase 11) and `FirestoreDecisionRepository.positions_for`
/`GraphReader.concession_ledger` already read any `Decision`/`CouncilPosition`
generically — so A49 Recorder needs no new repository method to persist a
Council's output. This file proves that bet against the real Firestore
emulator, the same way Phase 8's renegotiation flow already proved the
`Decision`/`CONCEDED_BY` round-trip for a non-Council `Decision`
(`test_traversals.py::TestConcessionLedger`) and Phase 1's
`test_traversals.py::TestDecisionsTouching` proved `CouncilPosition` reads
for a non-Council decision.

No new production code is added by this file. If anything below fails,
that is a real finding to report to the CTO, not something to route around.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from contracts.graph_types import (
    AgentId,
    CouncilPosition,
    Decision,
    DecisionStatus,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
    SourceRef,
)

from app.graph.decision_repository import FirestoreDecisionRepository
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import SeedResult
from tests.conftest import make_person, make_provenance

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


def _decision(node_id: str) -> Decision:
    return Decision(
        id=NodeId(node_id),
        provenance=make_provenance(derivation=Derivation.INFERRED, confidence=0.9),
        question="Do we relocate to the new flat in June?",
        trigger="lease-renewal-notice",
        status=DecisionStatus.BRIEFED,
        resolution_summary=None,
        rationale=None,
    )


def _position(
    node_id: str,
    *,
    decision_id: NodeId,
    held_by_agent: str,
    stance: Literal["supports", "opposes", "neutral"],
    branch_id: NodeId | None,
) -> CouncilPosition:
    return CouncilPosition(
        id=NodeId(node_id),
        provenance=Provenance(
            derivation=Derivation.INFERRED,
            source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="council-session"),
            confidence=0.85,
            deriving_agent=AgentId(held_by_agent),
            created_at=NOW,
        ),
        decision_id=decision_id,
        held_by_agent=AgentId(held_by_agent),
        stance=stance,
        branch_id=branch_id,
        reasoning=f"{held_by_agent}'s reasoning for this decision.",
        evidence_refs=(f"evidence-{held_by_agent}",),
    )


def _conceded_by(edge_id: str, *, decision_id: NodeId, person_id: NodeId) -> Edge:
    return Edge(
        id=EdgeId(edge_id),
        provenance=make_provenance(derivation=Derivation.INFERRED, confidence=0.9),
        edge_type=EdgeType.CONCEDED_BY,
        from_id=decision_id,
        to_id=person_id,
    )


class TestCouncilPositionRoundTrip:
    """`CouncilPosition` written via `FirestoreGraphWriter.write_node`,
    read back via `FirestoreDecisionRepository.positions_for` — the exact
    write/read pair A49 Recorder relies on."""

    def test_single_position_round_trips_with_every_field_intact(
        self, writer: FirestoreGraphWriter, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        decision = _decision("decision-council-single")
        writer.write_node(decision)
        position = _position(
            "position-a42-single",
            decision_id=decision.id,
            held_by_agent="A42",
            stance="supports",
            branch_id=NodeId("branch-stay-put"),
        )
        writer.write_node(position)

        repo = FirestoreDecisionRepository(store)
        found = repo.positions_for(decision.id)

        assert len(found) == 1
        (readback,) = found
        assert readback == position

    def test_positions_scoped_to_unrelated_decision_are_excluded(
        self, writer: FirestoreGraphWriter, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        decision_a = _decision("decision-council-a")
        decision_b = _decision("decision-council-b")
        writer.write_node(decision_a)
        writer.write_node(decision_b)
        position_a = _position(
            "position-a42-for-a",
            decision_id=decision_a.id,
            held_by_agent="A42",
            stance="supports",
            branch_id=None,
        )
        position_b = _position(
            "position-a43-for-b",
            decision_id=decision_b.id,
            held_by_agent="A43",
            stance="opposes",
            branch_id=None,
        )
        writer.write_node(position_a)
        writer.write_node(position_b)

        repo = FirestoreDecisionRepository(store)
        assert {p.id for p in repo.positions_for(decision_a.id)} == {position_a.id}
        assert {p.id for p in repo.positions_for(decision_b.id)} == {position_b.id}

    def test_unknown_decision_id_returns_empty(self, store: FirestoreGraphStore, seeded: SeedResult) -> None:
        repo = FirestoreDecisionRepository(store)
        assert repo.positions_for(NodeId("decision-does-not-exist")) == ()


class TestMultiplePositionsPerDecision:
    """Multiple specialists' `CouncilPosition`s for the *same* decision all
    come back from one `positions_for` call, distinguishable by
    `held_by_agent` — spec §5.2's own reason `COUNCIL_POSITION` exists at
    all ("what makes the council auditable rather than mystical")."""

    def test_one_position_per_specialist_all_returned_and_distinguishable(
        self, writer: FirestoreGraphWriter, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        decision = _decision("decision-council-relocation")
        writer.write_node(decision)

        specialists: tuple[tuple[str, str, Literal["supports", "opposes", "neutral"]], ...] = (
            ("position-a42-finance", "A42", "supports"),
            ("position-a43-care", "A43", "opposes"),
            ("position-a44-education", "A44", "neutral"),
            ("position-a45-logistics", "A45", "supports"),
            ("position-a46-legal", "A46", "opposes"),
        )
        written = [
            _position(node_id, decision_id=decision.id, held_by_agent=agent, stance=stance, branch_id=None)
            for node_id, agent, stance in specialists
        ]
        for position in written:
            writer.write_node(position)

        repo = FirestoreDecisionRepository(store)
        found = repo.positions_for(decision.id)

        assert len(found) == len(specialists)
        found_by_agent = {p.held_by_agent: p for p in found}
        assert set(found_by_agent) == {agent for _, agent, _ in specialists}
        for node_id, agent, stance in specialists:
            assert found_by_agent[AgentId(agent)].id == NodeId(node_id)
            assert found_by_agent[AgentId(agent)].stance == stance

    def test_does_not_leak_positions_belonging_to_other_decisions(
        self, writer: FirestoreGraphWriter, store: FirestoreGraphStore, seeded: SeedResult
    ) -> None:
        target = _decision("decision-council-target")
        other = _decision("decision-council-other")
        writer.write_node(target)
        writer.write_node(other)
        for node_id, decision, agent in (
            ("position-target-a42", target, "A42"),
            ("position-target-a43", target, "A43"),
            ("position-other-a44", other, "A44"),
        ):
            writer.write_node(
                _position(
                    node_id,
                    decision_id=decision.id,
                    held_by_agent=agent,
                    stance="supports",
                    branch_id=None,
                )
            )

        repo = FirestoreDecisionRepository(store)
        found_ids = {p.id for p in repo.positions_for(target.id)}
        assert found_ids == {NodeId("position-target-a42"), NodeId("position-target-a43")}


class TestConcededByRoundTrip:
    """`CONCEDED_BY` edge (`Decision` -> `Person`), written via
    `FirestoreGraphWriter.write_edge`, read back by
    `GraphReader.concession_ledger(person_id)` — the exact write/read pair
    the arbiter's trade-off statement (ADR-019 Decision 3) and A49 Recorder
    rely on. Phase 8's renegotiation flow already proved this exact
    round-trip for a non-Council `Decision`; this proves it again for a
    genuine Council decision."""

    def test_conceding_persons_own_ledger_call_returns_the_decision(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        decision = _decision("decision-council-concession")
        person = make_person("person-council-conceder", "Test Conceder")
        writer.write_node(decision)
        writer.write_node(person)
        writer.write_edge(
            _conceded_by("edge-council-concession", decision_id=decision.id, person_id=person.id)
        )

        ledger = reader.concession_ledger(person.id)

        assert len(ledger) == 1
        assert ledger[0] == decision

    def test_a_person_with_no_conceded_by_edge_gets_an_empty_ledger(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        person = make_person("person-council-no-concessions", "Never Concedes")
        # Not written at all — an unknown person id must also be tolerated,
        # not just a real person with zero edges.
        assert reader.concession_ledger(person.id) == ()

    def test_multiple_concessions_across_different_decisions_all_appear(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        person = make_person("person-council-repeat-conceder", "Repeat Conceder")
        writer.write_node(person)
        decision_one = _decision("decision-council-concession-one")
        decision_two = _decision("decision-council-concession-two")
        writer.write_node(decision_one)
        writer.write_node(decision_two)
        writer.write_edge(
            _conceded_by("edge-council-concession-one", decision_id=decision_one.id, person_id=person.id)
        )
        writer.write_edge(
            _conceded_by("edge-council-concession-two", decision_id=decision_two.id, person_id=person.id)
        )

        ledger = reader.concession_ledger(person.id)
        assert {d.id for d in ledger} == {decision_one.id, decision_two.id}

    def test_conceded_by_edge_does_not_leak_to_an_unrelated_person(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        decision = _decision("decision-council-concession-scoped")
        conceder = make_person("person-council-scoped-conceder", "Scoped Conceder")
        bystander = make_person("person-council-bystander", "Bystander")
        writer.write_node(decision)
        writer.write_node(conceder)
        writer.write_node(bystander)
        writer.write_edge(
            _conceded_by("edge-council-concession-scoped", decision_id=decision.id, person_id=conceder.id)
        )

        assert reader.concession_ledger(bystander.id) == ()
        assert {d.id for d in reader.concession_ledger(conceder.id)} == {decision.id}
