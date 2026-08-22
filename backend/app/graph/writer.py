"""`FirestoreGraphWriter` — the real, Firestore-backed
`contracts.repositories.GraphWriter` (replaces
`app.persistence`'s Phase 0 in-memory stub).

Every method here is provenance-guarded by
`app.persistence.firestore_store.FirestoreGraphStore` before any network
write — see that module's docstring for the versioning/supersession
mechanics. This class adds no behaviour beyond delegating, deliberately:
the provenance guard and the write mechanics live in exactly one place
(`FirestoreGraphStore`), never duplicated here.
"""

from __future__ import annotations

from typing import Any

from contracts.graph_types import Edge, NodeId

from app.persistence.firestore_store import FirestoreGraphStore


class FirestoreGraphWriter:
    """Structurally satisfies `contracts.repositories.GraphWriter` (T3 —
    internal graph writes, writer agents only)."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def write_node(self, node: Any) -> NodeId:
        """Writes a new node or a new version of an existing one.

        Raises:
            contracts.errors.ProvenanceMissing: `node`'s provenance is
                incomplete — rejected before any network call.
        """
        return self._store.put_node(node)

    def write_edge(self, edge: Edge) -> None:
        """Raises:
        contracts.errors.ProvenanceMissing: `edge`'s provenance is
            incomplete.
        """
        self._store.put_edge(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        """Sets `superseded_at` on the prior version at `old_node_id`
        (once only) and writes `new_node` as the new current version.

        Raises:
            contracts.errors.ProvenanceMissing: `new_node`'s provenance is
                incomplete — the prior version is left untouched in that
                case.
        """
        return self._store.supersede_node(old_node_id, new_node)
