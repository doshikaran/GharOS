"""A minimal, in-memory `contracts.repositories.GraphReader` test double —
originally for Phase 7 Ledger-agent unit tests (`test_reconciliation_
agent.py`) that need a real object satisfying the `GraphReader` Protocol
without a Firestore emulator, extended Phase 9 (`test_unblocker_agent.py`,
`test_friction_profile.py`) with real `neighbours` support, and extended
Phase 10 (`test_concierge_context.py`) with real `history` support for
A52's `booked_with` -> `completes_into` `Outcome` walk (ADR-016). Every
method beyond `series`/`neighbours`/`get_node`/`history` still raises
`NotImplementedError` — this fake is a narrow, real stand-in for the
specific operations its callers actually exercise, not a general-purpose
graph.

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_gemini_fakes.py`'s established pattern.
"""

from __future__ import annotations

from datetime import datetime

from contracts.graph_types import Decision, Edge, EdgeType, NodeId, Obligation, Outcome, PurchaseItem


class FakeGraphReader:
    """Structurally satisfies `contracts.repositories.GraphReader`."""

    def __init__(
        self,
        *,
        series_by_commitment: dict[str, tuple[object, ...]] | None = None,
        neighbours_by_node_and_type: dict[tuple[str, EdgeType], tuple[object, ...]] | None = None,
        nodes_by_id: dict[str, object] | None = None,
        history_by_entity: dict[str, tuple[Outcome, ...]] | None = None,
    ) -> None:
        self._series_by_commitment = series_by_commitment or {}
        self._neighbours_by_node_and_type = neighbours_by_node_and_type or {}
        self._nodes_by_id = nodes_by_id or {}
        self._history_by_entity = history_by_entity or {}
        self.series_calls: list[str] = []
        self.neighbours_calls: list[tuple[str, EdgeType]] = []
        self.get_node_calls: list[str] = []
        self.history_calls: list[str] = []

    def get_node(self, node_id: NodeId) -> object | None:
        self.get_node_calls.append(str(node_id))
        return self._nodes_by_id.get(str(node_id))

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        self.neighbours_calls.append((str(node_id), edge_type))
        return self._neighbours_by_node_and_type.get((str(node_id), edge_type), ())

    def path(self, from_id: NodeId, to_id: NodeId) -> tuple[Edge, ...]:
        raise NotImplementedError

    def blast_radius(self, node_id: NodeId, depth: int) -> tuple[object, ...]:
        raise NotImplementedError

    def conflicts(self, scope: str) -> tuple[Edge, ...]:
        raise NotImplementedError

    def dependency_chain(self, obligation_id: NodeId, *, max_depth: int = 25) -> tuple[Obligation, ...]:
        raise NotImplementedError

    def load(self, person_id: NodeId, window: tuple[datetime, datetime]) -> float:
        raise NotImplementedError

    def series(self, commitment_id: NodeId) -> tuple[object, ...]:
        self.series_calls.append(str(commitment_id))
        return self._series_by_commitment.get(str(commitment_id), ())

    def history(self, entity_id: NodeId) -> tuple[Outcome, ...]:
        self.history_calls.append(str(entity_id))
        return self._history_by_entity.get(str(entity_id), ())

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
        raise NotImplementedError


__all__ = ["FakeGraphReader"]
