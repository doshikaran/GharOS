"""`FirestoreGraphReader` — the real, Firestore-backed
`contracts.repositories.GraphReader`, implementing all 14 traversal
operations from spec §5.7 (replaces `app.persistence`'s Phase 0 in-memory
stub).

Single-hop operations (`neighbours`, `load`, `series`, `history`,
`concession_ledger`, `expected_but_absent`, `effort_evidence`) go straight
through `FirestoreGraphStore.edges_from` / `edges_to`, which are backed by
the `(from_id, edge_type)` / `(to_id, edge_type)` composite indexes
(ADR-001, `backend/migrations/firestore_indexes.py`).

Multi-hop operations (`path`, `blast_radius`) pull the full edge set once
via `FirestoreGraphStore.all_edges()` and walk it in memory — ADR-001
explicitly allows this at demo graph size ("hundreds of nodes") and
defers a graph-native store decision to a future ADR if it stops being
true.

**Scope semantics** (`scope: str` parameters — `conflicts`, `unexplained`,
`unverified`): the literal string `"all"` (or `""`) means "the whole
graph"; any other string is treated as a `NodeId` and restricts the
operation to nodes/edges touching that one node. Spec §5.7 does not pin
down `scope`'s exact shape beyond examples like "all unresolved collisions
this week" — named-subgraph scoping (e.g. "the Ledger subgraph") beyond
single-node restriction is not implemented in Phase 1; see this phase's
final report for the corresponding `docs/DEBT.md` candidate.
"""

from __future__ import annotations

from collections import deque
from datetime import datetime

from contracts.errors import ProvenanceMissing
from contracts.graph_types import (
    Branch,
    Constraint,
    CouncilPosition,
    Decision,
    Edge,
    EdgeType,
    LedgerEvent,
    NodeId,
    Obligation,
    Outcome,
    PurchaseItem,
)

from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.provenance_guard import subject_from_raw_document, validate_provenance

_UNRESTRICTED_SCOPES = ("all", "")


def _scope_node_id(scope: str) -> NodeId | None:
    """`None` means unrestricted (`scope in ("all", "")`); otherwise `scope`
    is a `NodeId` restricting the operation to that node."""
    return None if scope in _UNRESTRICTED_SCOPES else NodeId(scope)


class FirestoreGraphReader:
    """Structurally satisfies `contracts.repositories.GraphReader` (T0 —
    read-only graph access)."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    # -- basic lookup ----------------------------------------------------------

    def get_node(self, node_id: NodeId) -> object | None:
        return self._store.get_node(node_id)

    # -- 1. neighbours -----------------------------------------------------------

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        """spec §5.7 — e.g. obligations owned by a person. Bidirectional:
        returns the node at the *other* end of every `edge_type` edge
        touching `node_id`, regardless of which end `node_id` sits at."""
        other_ids: list[NodeId] = []
        for edge in self._store.edges_from(node_id, edge_type):
            other_ids.append(edge.to_id)
        for edge in self._store.edges_to(node_id, edge_type):
            other_ids.append(edge.from_id)
        found: list[object] = []
        for other_id in other_ids:
            node = self._store.get_node(other_id)
            if node is not None:
                found.append(node)
        return tuple(found)

    # -- 2. path -------------------------------------------------------------

    def path(self, from_id: NodeId, to_id: NodeId) -> tuple[Edge, ...]:
        """spec §5.7 — Path Explainer's (A9) core capability: why does this
        email affect Tuesday's lunch? Directed BFS shortest path following
        `edge.from_id -> edge.to_id` only. Empty tuple if no path exists or
        `from_id == to_id`."""
        if from_id == to_id:
            return ()

        adjacency: dict[NodeId, list[Edge]] = {}
        for edge in self._store.all_edges():
            adjacency.setdefault(edge.from_id, []).append(edge)

        frontier: deque[NodeId] = deque([from_id])
        came_from: dict[NodeId, Edge] = {}
        visited = {from_id}
        while frontier:
            current = frontier.popleft()
            if current == to_id:
                break
            for edge in adjacency.get(current, []):
                if edge.to_id in visited:
                    continue
                visited.add(edge.to_id)
                came_from[edge.to_id] = edge
                frontier.append(edge.to_id)

        if to_id not in came_from:
            return ()

        chain: list[Edge] = []
        cursor = to_id
        while cursor in came_from:
            edge = came_from[cursor]
            chain.append(edge)
            cursor = edge.from_id
        chain.reverse()
        return tuple(chain)

    # -- 3. blast_radius -------------------------------------------------------

    def blast_radius(self, node_id: NodeId, depth: int) -> tuple[object, ...]:
        """spec §5.7 — what breaks if we relocate in June? Undirected BFS
        up to `depth` hops — impact propagates along an edge in either
        direction, unlike `path`."""
        if depth < 0:
            return ()

        all_edges = self._store.all_edges()
        visited = {node_id}
        frontier = {node_id}
        result: list[object] = []
        for _ in range(depth):
            next_frontier: set[NodeId] = set()
            for edge in all_edges:
                for src, dst in ((edge.from_id, edge.to_id), (edge.to_id, edge.from_id)):
                    if src in frontier and dst not in visited:
                        next_frontier.add(dst)
            if not next_frontier:
                break
            for nid in next_frontier:
                visited.add(nid)
                node = self._store.get_node(nid)
                if node is not None:
                    result.append(node)
            frontier = next_frontier
        return tuple(result)

    # -- 4. conflicts ------------------------------------------------------------

    def conflicts(self, scope: str) -> tuple[Edge, ...]:
        """spec §5.7 — all unresolved `conflicts_with`/`violates` edges in
        scope. "Unresolved" = the edge itself has not been superseded
        (`provenance.superseded_at is None`) — a conflict is closed by
        superseding the edge that recorded it, not by deleting it."""
        restrict_to = _scope_node_id(scope)
        found: list[Edge] = []
        candidates: tuple[Edge, ...]
        if restrict_to is None:
            candidates = tuple(
                edge
                for edge in self._store.all_edges()
                if edge.edge_type in (EdgeType.CONFLICTS_WITH, EdgeType.VIOLATES)
            )
        else:
            candidates = (
                *self._store.edges_from(restrict_to, EdgeType.CONFLICTS_WITH),
                *self._store.edges_from(restrict_to, EdgeType.VIOLATES),
                *self._store.edges_to(restrict_to, EdgeType.CONFLICTS_WITH),
                *self._store.edges_to(restrict_to, EdgeType.VIOLATES),
            )
        for edge in candidates:
            if edge.provenance.superseded_at is None:
                found.append(edge)
        return tuple(found)

    # -- 5. load -------------------------------------------------------------

    def load(self, person_id: NodeId, window: tuple[datetime, datetime]) -> float:
        """spec §5.7 — a person's obligation load in a time window (Fair
        Allocator input): total `effort_estimate_minutes` across
        obligations `owned_by` this person, due within `window`."""
        start, end = window
        total_minutes = 0.0
        for edge in self._store.edges_to(person_id, EdgeType.OWNED_BY):
            obligation = self._store.get_node(edge.from_id)
            if not isinstance(obligation, Obligation):
                continue
            if obligation.due_at is None or not (start <= obligation.due_at <= end):
                continue
            total_minutes += obligation.effort_estimate_minutes or 0
        return total_minutes

    # -- 6. series -----------------------------------------------------------

    def series(self, commitment_id: NodeId) -> tuple[object, ...]:
        """spec §5.7 — all LEDGER_EVENTs `belongs_to` a RECURRING_COMMITMENT."""
        events: list[object] = []
        for edge in self._store.edges_to(commitment_id, EdgeType.BELONGS_TO):
            event = self._store.get_node(edge.from_id)
            if event is not None:
                events.append(event)
        return tuple(events)

    # -- 7. history ------------------------------------------------------------

    def history(self, entity_id: NodeId) -> tuple[Outcome, ...]:
        """spec §5.7 — all OUTCOMEs this entity `completes_into` (Calibration
        input)."""
        outcomes: list[Outcome] = []
        for edge in self._store.edges_from(entity_id, EdgeType.COMPLETES_INTO):
            outcome = self._store.get_node(edge.to_id)
            if isinstance(outcome, Outcome):
                outcomes.append(outcome)
        return tuple(outcomes)

    # -- 8. decisions_touching -----------------------------------------------

    def decisions_touching(self, entity_id: NodeId) -> tuple[Decision, ...]:
        """spec §5.7 — every past DECISION involving `entity_id`, whether
        directly (any edge touching it points at/from a DECISION) or
        indirectly (via a BRANCH or COUNCIL_POSITION belonging to one)."""
        decision_ids: set[NodeId] = set()
        touching = (*self._store.edges_from(entity_id), *self._store.edges_to(entity_id))
        for edge in touching:
            other_id = edge.to_id if edge.from_id == entity_id else edge.from_id
            other = self._store.get_node(other_id)
            if isinstance(other, Decision):
                decision_ids.add(other.id)
            elif isinstance(other, Branch | CouncilPosition):
                decision_ids.add(other.decision_id)
        decisions = (self._store.get_node(did) for did in decision_ids)
        return tuple(d for d in decisions if isinstance(d, Decision))

    # -- 9. concession_ledger --------------------------------------------------

    def concession_ledger(self, person_id: NodeId) -> tuple[Decision, ...]:
        """spec §5.7 — DECISIONs where this person has a `conceded_by`
        edge, for fairness-over-time tracking (Council input)."""
        decisions: list[Decision] = []
        for edge in self._store.edges_to(person_id, EdgeType.CONCEDED_BY):
            decision = self._store.get_node(edge.from_id)
            if isinstance(decision, Decision):
                decisions.append(decision)
        return tuple(decisions)

    # -- 10. unexplained -------------------------------------------------------

    def unexplained(self, scope: str) -> tuple[NodeId, ...]:
        """spec §5.7 — nodes lacking provenance. MUST be empty on a
        correctly-written graph — an integrity check, not a normal query
        path. Independent of the write guard on purpose: re-validates every
        stored node rather than trusting that every write went through
        `FirestoreGraphWriter`. Scans raw, undecoded documents
        (`FirestoreGraphStore.all_current_node_documents`) rather than
        typed nodes — a structurally corrupted document (e.g. missing
        `provenance` entirely) must be *reported*, not crash this scan
        before it can be reported."""
        restrict_to = _scope_node_id(scope)
        bad: list[NodeId] = []
        for _node_type, doc_id, raw in self._store.all_current_node_documents():
            if restrict_to is not None and doc_id != str(restrict_to):
                continue
            subject = subject_from_raw_document(doc_id, raw)
            try:
                validate_provenance(subject)
            except ProvenanceMissing:
                bad.append(NodeId(doc_id))
        return tuple(bad)

    # -- 11. unverified --------------------------------------------------------

    def unverified(self, scope: str) -> tuple[NodeId, ...]:
        """spec §5.7 — graph claims with no real-world verification
        evidence behind them: OBLIGATIONs with no `discharges`/`verifies`/
        `contradicts` edge pointing at them, and CONSTRAINTs with no
        `verifies`/`contradicts` edge pointing at them."""
        restrict_to = _scope_node_id(scope)
        unverified_ids: list[NodeId] = []

        for obligation in self._store.all_current_nodes((Obligation,)):
            if restrict_to is not None and obligation.id != restrict_to:
                continue
            verifying = (
                *self._store.edges_to(obligation.id, EdgeType.DISCHARGES),
                *self._store.edges_to(obligation.id, EdgeType.VERIFIES),
                *self._store.edges_to(obligation.id, EdgeType.CONTRADICTS),
            )
            if not verifying:
                unverified_ids.append(obligation.id)

        for constraint in self._store.all_current_nodes((Constraint,)):
            if restrict_to is not None and constraint.id != restrict_to:
                continue
            verifying = (
                *self._store.edges_to(constraint.id, EdgeType.VERIFIES),
                *self._store.edges_to(constraint.id, EdgeType.CONTRADICTS),
            )
            if not verifying:
                unverified_ids.append(constraint.id)

        return tuple(unverified_ids)

    # -- 12. expected_but_absent ------------------------------------------------

    def expected_but_absent(self, constraint_id: NodeId) -> tuple[NodeId, ...]:
        """spec §5.7 — SOURCE_DOCUMENTs where expected evidence for a
        constraint never appeared; backs the `absent_from` edge and the
        Pattern Miner's silent-non-compliance signal (spec §5.5)."""
        return tuple(edge.to_id for edge in self._store.edges_from(constraint_id, EdgeType.ABSENT_FROM))

    # -- 13. spend_by_category ---------------------------------------------------

    def spend_by_category(self, window: tuple[datetime, datetime]) -> dict[str, float]:
        """spec §5.7 — real spend from PURCHASE_ITEM line items, not
        estimates."""
        start, end = window
        totals: dict[str, float] = {}
        ledger_event_cache: dict[NodeId, LedgerEvent | None] = {}

        for item in self._store.all_current_nodes((PurchaseItem,)):
            if item.ledger_event_id not in ledger_event_cache:
                node = self._store.get_node(item.ledger_event_id)
                ledger_event_cache[item.ledger_event_id] = node if isinstance(node, LedgerEvent) else None
            ledger_event = ledger_event_cache[item.ledger_event_id]
            if ledger_event is None or not (start <= ledger_event.occurred_at <= end):
                continue
            category = item.normalized_category or "uncategorised"
            totals[category] = totals.get(category, 0.0) + item.line_total
        return totals

    # -- 14. effort_evidence ------------------------------------------------------

    def effort_evidence(
        self, person_id: NodeId, window: tuple[datetime, datetime]
    ) -> tuple[PurchaseItem, ...]:
        """spec §5.7 — who actually did the runs, from `evidences_effort`
        edges; a primary Fair Allocator input (spec §5.5)."""
        start, end = window
        items: list[PurchaseItem] = []
        for edge in self._store.edges_to(person_id, EdgeType.EVIDENCES_EFFORT):
            source = self._store.get_node(edge.from_id)
            if not isinstance(source, PurchaseItem):
                # spec §5.3 allows this edge from LEDGER_EVENT too, but the
                # protocol's return type is tuple[PurchaseItem, ...] — a
                # LEDGER_EVENT-sourced edge has no PurchaseItem to return.
                continue
            ledger_event = self._store.get_node(source.ledger_event_id)
            if isinstance(ledger_event, LedgerEvent) and not (start <= ledger_event.occurred_at <= end):
                continue
            items.append(source)
        return tuple(items)
