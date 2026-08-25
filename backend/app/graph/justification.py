"""`JustificationExplainer` — the path explainer behind
`GET /graph/nodes/{node_id}/justification` (PHASES.md Phase 6 E1 work
item: "path query API"; spec §5.7's Path Explainer, A9, at a conclusion
rather than an (a, b) pair).

**Not part of `contracts.repositories.GraphReader`.** Mirrors the
precedent `FirestoreGraphReader.dependency_chain` set in Phase 4
(ADR-011's eventual promotion candidate): a concrete-only reference
implementation, reachable by any caller holding a `FirestoreGraphStore`
(or, at the HTTP boundary, `app.api.graph_router`), built and reported
back to the CTO rather than added to the frozen Protocol directly. If a
second Protocol-typed caller later needs this without depending on
`app.graph` concretely, that promotion is a CTO-owned `contracts/`
change, not something made here.

**Algorithm.** BFS from `node_id`, walking edges in *either* direction
(an edge's own defined direction may point away from or toward the
conclusion depending on the edge type — e.g. `implies` is
SOURCE_DOCUMENT -> OBLIGATION, so from an OBLIGATION the walk goes
*backward* along an incoming `implies` edge to reach its document),
restricted to `JUSTIFICATORY_EDGE_TYPES` below. Depth-bounded
(`MAX_JUSTIFICATION_DEPTH`, matching `dependency_chain`'s own precedent)
and node-count-bounded (`MAX_JUSTIFICATION_NODES`) — this walk must never
crawl the whole graph for one node.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Any

from contracts.graph_types import Edge, EdgeType, NodeId, SourceDocument

from app.graph.errors import NodeNotFound
from app.persistence.firestore_store import FirestoreGraphStore

JUSTIFICATORY_EDGE_TYPES: frozenset[EdgeType] = frozenset(
    {
        EdgeType.STATES,
        EdgeType.IMPLIES,
        EdgeType.DEPENDS_ON,
        EdgeType.GROUNDED_IN,
        EdgeType.SUPPORTS,
        EdgeType.OPPOSES,
        EdgeType.RESOLVED_AS,
        EdgeType.DISCHARGES,
        EdgeType.VERIFIES,
        EdgeType.CONTRADICTS,
        EdgeType.COMPLETES_INTO,
        EdgeType.PREDICTED_BY,
        EdgeType.LEARNED_FROM,
        EdgeType.VIOLATES,
        EdgeType.CONFLICTS_WITH,
        EdgeType.PAID_FOR,
        EdgeType.LINE_ITEM_OF,
        EdgeType.BELONGS_TO,
        EdgeType.OWED_TO,
        EdgeType.COVERS,
        EdgeType.ACTS_ON,
        EdgeType.AUTHORIZES,
    }
)
"""The fixed, named, documented "this exists/is-true/is-decided *because
of* that" edge set (this phase's frozen wire contract) — deliberately
excludes purely structural/ownership edges that carry no justificatory
content: OWNED_BY, BENEFITS, CONSTRAINS, APPROVED_BY, SUPERSEDES,
CONTAINS, CONCEDED_BY, BOOKED_WITH, SUBSTITUTES, EVIDENCES_EFFORT,
ABSENT_FROM."""

MAX_JUSTIFICATION_DEPTH = 25
"""Matches `FirestoreGraphReader.dependency_chain`'s existing Phase 4
precedent — a defensive ceiling, not a tuning knob."""

MAX_JUSTIFICATION_NODES = 200
"""Sane bound so this walk can never crawl the whole graph for one node."""


@dataclass(frozen=True, slots=True)
class JustificationStep:
    node_id: str
    depth: int
    via_edge: dict[str, str] | None
    """`None` only for the root step (depth 0). Otherwise
    `{"id", "type", "from_id", "to_id"}` — this phase's frozen `via_edge`
    wire shape, deliberately smaller than `/graph/snapshot`'s own edge
    shape (no `derivation`/`confidence`/`is_conflict`)."""


@dataclass(frozen=True, slots=True)
class JustificationSourceDocument:
    id: str
    channel: str
    region: str | None
    """The region, within this document, that the path used to reach it —
    taken from the neighbouring node's own `provenance.source_ref` when
    that `source_ref` points at this exact document (the common case: the
    node one hop away from a SOURCE_DOCUMENT in the walk is very often the
    node that document's extraction directly produced). `None` when no
    such region is resolvable from the path taken."""


@dataclass(frozen=True, slots=True)
class JustificationResult:
    root_node_id: str
    steps: tuple[JustificationStep, ...]
    source_documents: tuple[JustificationSourceDocument, ...]


def _edge_summary(edge: Edge) -> dict[str, str]:
    """This phase's frozen `via_edge` wire shape."""
    return {
        "id": str(edge.id),
        "type": edge.edge_type.value,
        "from_id": str(edge.from_id),
        "to_id": str(edge.to_id),
    }


class JustificationExplainer:
    """Walks the justificatory-edge-type subgraph from a conclusion node
    back to its evidentiary SOURCE_DOCUMENT roots."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def explain(
        self,
        node_id: NodeId,
        *,
        max_depth: int = MAX_JUSTIFICATION_DEPTH,
        max_nodes: int = MAX_JUSTIFICATION_NODES,
    ) -> JustificationResult:
        """Returns the walkable justification chain back to `node_id`'s
        evidentiary roots.

        Raises:
            NodeNotFound: `node_id` does not resolve to any current node.
        """
        root = self._store.get_node(node_id)
        if root is None:
            raise NodeNotFound(node_id=str(node_id))

        steps: list[JustificationStep] = [JustificationStep(node_id=str(node_id), depth=0, via_edge=None)]
        visited: set[NodeId] = {node_id}
        source_documents: dict[str, JustificationSourceDocument] = {}

        self._record_if_source_document(root, reached_from=None, out=source_documents)

        frontier: deque[tuple[NodeId, int]] = deque([(node_id, 0)])
        while frontier and len(visited) < max_nodes:
            current_id, depth = frontier.popleft()
            if depth >= max_depth:
                continue
            current_node = self._store.get_node(current_id)
            for edge in self._justificatory_edges_touching(current_id):
                if len(visited) >= max_nodes:
                    break
                neighbour_id = edge.to_id if edge.from_id == current_id else edge.from_id
                if neighbour_id in visited:
                    continue
                visited.add(neighbour_id)
                neighbour_depth = depth + 1
                steps.append(
                    JustificationStep(
                        node_id=str(neighbour_id), depth=neighbour_depth, via_edge=_edge_summary(edge)
                    )
                )
                neighbour_node = self._store.get_node(neighbour_id)
                if neighbour_node is not None:
                    self._record_if_source_document(
                        neighbour_node, reached_from=current_node, out=source_documents
                    )
                    frontier.append((neighbour_id, neighbour_depth))

        return JustificationResult(
            root_node_id=str(node_id),
            steps=tuple(steps),
            source_documents=tuple(source_documents.values()),
        )

    def _justificatory_edges_touching(self, node_id: NodeId) -> list[Edge]:
        edges = [*self._store.edges_from(node_id), *self._store.edges_to(node_id)]
        return [edge for edge in edges if edge.edge_type in JUSTIFICATORY_EDGE_TYPES]

    @staticmethod
    def _record_if_source_document(
        node: Any,
        *,
        reached_from: Any,
        out: dict[str, JustificationSourceDocument],
    ) -> None:
        if not isinstance(node, SourceDocument):
            return
        region: str | None = None
        if reached_from is not None:
            provenance = getattr(reached_from, "provenance", None)
            source_ref = getattr(provenance, "source_ref", None) if provenance is not None else None
            if source_ref is not None and source_ref.source_document_id == node.id:
                region = source_ref.region
        out[str(node.id)] = JustificationSourceDocument(id=str(node.id), channel=node.channel, region=region)
