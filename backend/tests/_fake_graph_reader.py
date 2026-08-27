"""A minimal, in-memory `contracts.repositories.GraphReader` test double —
for Phase 7 Ledger-agent unit tests (`test_reconciliation_agent.py`) that
need a real object satisfying the `GraphReader` Protocol without a
Firestore emulator. Every method beyond `series` raises
`NotImplementedError` — this fake exists only to prove
`ReconciliationAgent.fetch_series` goes through the T0 `graph_reader` tool
for real, not to be a general-purpose graph stand-in.

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_gemini_fakes.py`'s established pattern.
"""

from __future__ import annotations

from datetime import datetime

from contracts.graph_types import Decision, Edge, EdgeType, NodeId, Obligation, Outcome, PurchaseItem


class FakeGraphReader:
    """Structurally satisfies `contracts.repositories.GraphReader`."""

    def __init__(self, *, series_by_commitment: dict[str, tuple[object, ...]] | None = None) -> None:
        self._series_by_commitment = series_by_commitment or {}
        self.series_calls: list[str] = []

    def get_node(self, node_id: NodeId) -> object | None:
        raise NotImplementedError

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        raise NotImplementedError

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
        raise NotImplementedError


__all__ = ["FakeGraphReader"]
