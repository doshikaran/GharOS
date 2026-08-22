"""`FirestoreDecisionRepository` — real, Firestore-backed
`contracts.repositories.DecisionRepository`.

DECISION, BRANCH, and COUNCIL_POSITION records are permanent — never
pruned, at any phase (spec §5.2, §20; E1 charter "Never do"). This
repository only ever reads; nothing in this package deletes a Decision,
Branch, or CouncilPosition, and Phase 14's Graph Maintainer must preserve
that even when it gains real pruning logic for other node types.
"""

from __future__ import annotations

from contracts.graph_types import Branch, CouncilPosition, Decision, NodeId

from app.persistence.firestore_store import FirestoreGraphStore


class FirestoreDecisionRepository:
    """Structurally satisfies `contracts.repositories.DecisionRepository`."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def get_decision(self, decision_id: NodeId) -> Decision | None:
        node = self._store.get_node(decision_id)
        return node if isinstance(node, Decision) else None

    def branches_for(self, decision_id: NodeId) -> tuple[Branch, ...]:
        return tuple(
            branch for branch in self._store.all_current_nodes((Branch,)) if branch.decision_id == decision_id
        )

    def positions_for(self, decision_id: NodeId) -> tuple[CouncilPosition, ...]:
        return tuple(
            position
            for position in self._store.all_current_nodes((CouncilPosition,))
            if position.decision_id == decision_id
        )
