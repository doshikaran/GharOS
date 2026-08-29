"""Tests for `app.agents.fair_allocator.context` — the real-graph
assembly helpers for A18 (observed-effort-to-task correlation) and A21
(household-total load aggregation).

`resolve_observed_effort_signals` is the concrete answer to E1's Phase 8
final-report finding: correlating a `PurchaseItem` to a specific task
needs a second hop (`neighbours(item.id, EdgeType.DISCHARGES)`) beyond
`GraphReader.effort_evidence` alone. These tests exercise that second hop
directly against a minimal, purpose-built fake `GraphReader` — no
Firestore emulator needed (E1's `effort_evidence`/`neighbours` are already
proven against the real emulator elsewhere; this module only tests the
two-hop composition logic this package adds on top).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from contracts.graph_types import (
    AgentId,
    Decision,
    Derivation,
    Edge,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Provenance,
    PurchaseItem,
    SourceRef,
)

from app.agents.fair_allocator.context import household_total_load, resolve_observed_effort_signals

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
_WINDOW = (_NOW - timedelta(days=30), _NOW)


def _provenance() -> Provenance:
    return Provenance(
        derivation=Derivation.EXTRACTED,
        source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="whole-document"),
        confidence=0.9,
        deriving_agent=AgentId("A3"),
        created_at=_NOW,
    )


def _obligation(node_id: str, title: str) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=_provenance(),
        title=title,
        obligation_type="chore",
        due_at=None,
        must_start_by=None,
        effort_estimate_minutes=30,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _purchase_item(node_id: str, description: str) -> PurchaseItem:
    return PurchaseItem(
        id=NodeId(node_id),
        provenance=_provenance(),
        ledger_event_id=NodeId("ledger-1"),
        description=description,
        normalized_category="groceries",
        quantity=1.0,
        unit_price=100.0,
        line_total=100.0,
    )


class _FakeGraphReader:
    """A minimal, purpose-built fake supporting exactly `effort_evidence`,
    `neighbours`, and `load` — everything else raises `NotImplementedError`,
    matching `tests/_fake_graph_reader.py`'s established narrow-fake
    pattern."""

    def __init__(
        self,
        *,
        effort_items_by_person: dict[str, tuple[PurchaseItem, ...]] | None = None,
        discharges_by_item: dict[str, tuple[Obligation, ...]] | None = None,
        load_by_person: dict[str, float] | None = None,
    ) -> None:
        self._effort_items_by_person = effort_items_by_person or {}
        self._discharges_by_item = discharges_by_item or {}
        self._load_by_person = load_by_person or {}

    def get_node(self, node_id: NodeId) -> object | None:
        raise NotImplementedError

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        if edge_type is EdgeType.DISCHARGES:
            return self._discharges_by_item.get(str(node_id), ())
        raise NotImplementedError

    def path(self, from_id: NodeId, to_id: NodeId) -> tuple[Edge, ...]:
        raise NotImplementedError

    def blast_radius(self, node_id: NodeId, depth: int) -> tuple[object, ...]:
        raise NotImplementedError

    def blast_radius_multi(self, node_ids: tuple[NodeId, ...], depth: int) -> tuple[object, ...]:
        raise NotImplementedError

    def conflicts(self, scope: str) -> tuple[Edge, ...]:
        raise NotImplementedError

    def dependency_chain(self, obligation_id: NodeId, *, max_depth: int = 25) -> tuple[Obligation, ...]:
        raise NotImplementedError

    def load(self, person_id: NodeId, window: tuple[datetime, datetime]) -> float:
        return self._load_by_person.get(str(person_id), 0.0)

    def series(self, commitment_id: NodeId) -> tuple[object, ...]:
        raise NotImplementedError

    def history(self, entity_id: NodeId) -> tuple[Outcome, ...]:
        raise NotImplementedError

    def outcome_variance(self, tag: str) -> tuple[Outcome, ...]:
        raise NotImplementedError

    def decisions_touching(self, entity_id: NodeId) -> tuple[Decision, ...]:
        raise NotImplementedError

    def concession_ledger(self, person_id: NodeId) -> tuple[Decision, ...]:
        raise NotImplementedError

    def unexplained(self, scope: str) -> tuple[NodeId, ...]:
        raise NotImplementedError

    def unverified(self, scope: str) -> tuple[NodeId, ...]:
        raise NotImplementedError

    def expected_but_absent(self, constraint_id: NodeId) -> tuple[NodeId, ...]:
        raise NotImplementedError

    def spend_by_category(self, window: tuple[datetime, datetime]) -> dict[str, float]:
        raise NotImplementedError

    def effort_evidence(
        self, person_id: NodeId, window: tuple[datetime, datetime]
    ) -> tuple[PurchaseItem, ...]:
        return self._effort_items_by_person.get(str(person_id), ())


class TestResolveObservedEffortSignals:
    def test_purchase_item_correctly_correlated_to_its_discharged_task(self) -> None:
        item = _purchase_item("item-1", "groceries for the week")
        obligation = _obligation("obligation-groceries", "Weekly grocery run")
        reader = _FakeGraphReader(
            effort_items_by_person={"person-priya": (item,)},
            discharges_by_item={"item-1": (obligation,)},
        )

        signals = resolve_observed_effort_signals(reader, person_id=NodeId("person-priya"), window=_WINDOW)

        assert len(signals) == 1
        assert signals[0].task_id == NodeId("obligation-groceries")
        assert signals[0].purchase_item_id == NodeId("item-1")
        assert signals[0].description == "groceries for the week"

    def test_purchase_item_with_no_discharges_edge_is_excluded_not_guessed(self) -> None:
        """Real effort evidence with no task correlation is simply not
        usable as per-task valuation evidence — never guessed at which
        task it might belong to."""
        item = _purchase_item("item-2", "an unrelated purchase")
        reader = _FakeGraphReader(effort_items_by_person={"person-priya": (item,)}, discharges_by_item={})

        signals = resolve_observed_effort_signals(reader, person_id=NodeId("person-priya"), window=_WINDOW)

        assert signals == ()

    def test_one_item_discharging_two_obligations_produces_two_signals(self) -> None:
        item = _purchase_item("item-3", "combined errand receipt")
        obligation_a = _obligation("obligation-a", "Task A")
        obligation_b = _obligation("obligation-b", "Task B")
        reader = _FakeGraphReader(
            effort_items_by_person={"person-priya": (item,)},
            discharges_by_item={"item-3": (obligation_a, obligation_b)},
        )

        signals = resolve_observed_effort_signals(reader, person_id=NodeId("person-priya"), window=_WINDOW)

        assert {s.task_id for s in signals} == {NodeId("obligation-a"), NodeId("obligation-b")}


class TestHouseholdTotalLoad:
    def test_returns_real_per_person_load(self) -> None:
        reader = _FakeGraphReader(load_by_person={"person-priya": 12.0, "person-raj": 8.0})

        totals = household_total_load(
            reader, person_ids=(NodeId("person-priya"), NodeId("person-raj")), window=_WINDOW
        )

        assert totals == {NodeId("person-priya"): 12.0, NodeId("person-raj"): 8.0}
