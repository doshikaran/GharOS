"""`FirestoreObligationRepository` — real, Firestore-backed
`contracts.repositories.ObligationRepository`."""

from __future__ import annotations

from contracts.graph_types import EdgeType, NodeId, Obligation, ObligationStatus

from app.persistence.firestore_store import FirestoreGraphStore

_CLOSED_STATUSES = (ObligationStatus.COMPLETED, ObligationStatus.DROPPED, ObligationStatus.SUPERSEDED)


class FirestoreObligationRepository:
    """Structurally satisfies `contracts.repositories.ObligationRepository`."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def get(self, obligation_id: NodeId) -> Obligation | None:
        node = self._store.get_node(obligation_id)
        return node if isinstance(node, Obligation) else None

    def open_obligations_for(self, person_id: NodeId) -> tuple[Obligation, ...]:
        owned_ids = {edge.from_id for edge in self._store.edges_to(person_id, EdgeType.OWNED_BY)}
        return tuple(
            obligation
            for obligation in self._store.all_current_nodes((Obligation,))
            if obligation.id in owned_ids and obligation.status not in _CLOSED_STATUSES
        )

    def unassigned(self) -> tuple[Obligation, ...]:
        owned_ids = {edge.from_id for edge in self._store.all_edges() if edge.edge_type == EdgeType.OWNED_BY}
        return tuple(
            obligation
            for obligation in self._store.all_current_nodes((Obligation,))
            if obligation.id not in owned_ids
        )
