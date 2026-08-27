"""A minimal, in-memory `contracts.repositories.GraphWriter` test double —
for Phase 7 Ledger-agent unit tests (`test_staff_payroll_agent.py`) that
need a real object satisfying the `GraphWriter` Protocol without a
Firestore emulator (the real, provenance-guarded, Firestore-backed proof
lives in `test_graph_write_tool.py`, run against the emulator).

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_gemini_fakes.py` / `_fake_idempotency_store.py`'s established
pattern.
"""

from __future__ import annotations

from typing import Any

from contracts.graph_types import Edge, NodeId


class FakeGraphWriter:
    """Structurally satisfies `contracts.repositories.GraphWriter`. Stores
    every written node by its own `.id` — no provenance guard here (that
    is E1's real writer's job); this fake exists to let A34's unit tests
    prove *what* gets written, not to re-prove the provenance invariant."""

    def __init__(self) -> None:
        self.nodes: dict[NodeId, Any] = {}
        self.edges: list[Edge] = []
        self.write_node_calls = 0

    def write_node(self, node: Any) -> NodeId:
        self.write_node_calls += 1
        self.nodes[node.id] = node
        return node.id  # type: ignore[no-any-return]

    def write_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        self.nodes[new_node.id] = new_node
        return new_node.id  # type: ignore[no-any-return]


__all__ = ["FakeGraphWriter"]
