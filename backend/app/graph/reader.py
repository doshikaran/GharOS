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

from app.graph.obligation_lifecycle import CLOSED_OBLIGATION_STATUSES
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.provenance_guard import subject_from_raw_document, validate_provenance

_UNRESTRICTED_SCOPES = ("all", "")

_MAX_DEPENDENCY_CHAIN_DEPTH = 64
"""Cycle/runaway-safety bound for `dependency_chain`. A well-formed
household's DEPENDS_ON chains are tiny (single digits of hops); this is a
defensive ceiling against malformed/cyclic data, not a tuning knob."""


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

    # -- blast_radius_multi (Phase 11 addition, ADR-017, NOT one of the 14 spec §5.7 ops) --

    def blast_radius_multi(self, node_ids: tuple[NodeId, ...], depth: int) -> tuple[object, ...]:
        """ADR-017 — "blast radius at decision scale" (PHASES.md Phase 11,
        E1 work item): the Path Simulator (A37) seeds this from every real
        anchor entity a decision touches (home, school, staff `Person`
        nodes, recurring `Obligation`s), not one node.

        **Implementation choice, documented per this method's own brief:**
        this is a **separate, honest, per-seed-union implementation**
        (`blast_radius(seed, depth)` called once per distinct seed,
        results unioned and deduplicated by node id) — **not** a single
        shared-frontier multi-source BFS pass, despite the Protocol
        docstring's "one traversal pass" framing being the aspiration.

        A single-pass multi-source BFS was tried first and rejected: the
        reference definition ("correctness-equivalent to calling
        `blast_radius` once per seed and unioning") has a real subtlety a
        naive shared-frontier BFS gets wrong — `blast_radius(A, depth)`
        excludes *only* `A` from its own result, but a *different* seed
        `B` genuinely reachable within `depth` hops of `A` is an entirely
        ordinary node from `A`'s BFS's point of view and belongs in `A`'s
        contribution to the union. A standard multi-source BFS that
        pre-marks every seed "visited" before it starts (the usual
        efficiency habit, needed to stop the search from re-expanding a
        source node) silently drops such mutually-reachable seeds from
        the result — `test_graph_reader_simulator_ops.py`'s literal
        union-equivalence test (parametrised across seed/depth
        combinations, comparing node-id sets, not spot-checking) caught
        exactly this on real seeded data. The reverse fix (never
        pre-marking seeds visited) then let a *single* seed's own cyclic
        paths rediscover itself in later rounds instead, which
        `blast_radius` itself never does. Making one shared BFS honour
        both "a seed can be found via another seed" and "a seed can never
        find only itself" needs per-source-seed visited bookkeeping inside
        one pass — real complexity for a method the brief itself says is
        allowed to be "a separate correct implementation proven equivalent
        by test" instead. Given a demo-scale graph (ADR-001: "hundreds of
        nodes"), running `blast_radius` a handful of times (one per real
        anchor entity a decision touches — typically single digits) is not
        a performance concern; correctness-by-construction against
        already-Gate-1-proven code is worth more here than the constant-
        factor saving of a hand-rolled multi-source variant.

        Semantics mirror `blast_radius` exactly, generalised to multiple
        seeds: a node is included iff *some* seed's own `blast_radius`
        call includes it — i.e. iff its distance from that seed is within
        `depth`, per this method's Protocol docstring. A seed is excluded
        from its *own* contribution (matching `blast_radius`'s own
        convention) but **can** appear in the result via a different
        seed's contribution, if genuinely reachable from it within
        `depth`. Duplicate seed ids are naturally deduplicated (calling
        `blast_radius` twice on the same id contributes the same set
        twice); unknown seed ids are tolerated (`blast_radius` itself
        already returns `()` for a `node_id` with no edges/no node).
        """
        if depth < 0 or not node_ids:
            return ()

        seen_ids: set[NodeId] = set()
        result: list[object] = []
        for seed in dict.fromkeys(node_ids):  # de-dup, preserve first-seen order
            for node in self.blast_radius(seed, depth):
                node_id = node.id  # type: ignore[attr-defined]
                if node_id not in seen_ids:
                    seen_ids.add(node_id)
                    result.append(node)
        return tuple(result)

    # -- outcome_variance (Phase 11 addition, ADR-017, NOT one of the 14 spec §5.7 ops) --

    def outcome_variance(self, tag: str) -> tuple[Outcome, ...]:
        """ADR-017 — cross-entity OUTCOME variance by decision category:
        every current `Outcome` node whose `attribution_tags` contains
        `tag`, independent of which entity `completes_into` it (unlike
        `history(entity)`, which is single-entity). Feeds Calibration's
        (A39) "this household's own variance" for a category such as
        `"relocation"` or `"school_transition"` (see `gharos-graph-model`
        for the full tag vocabulary — both the Phase 10 provider-
        reliability tags and the Phase 11 decision-category tags share
        this one field).

        Full-graph scan by design (no entity anchor to restrict from) —
        same performance envelope as `unexplained`/`unverified`'s existing
        full-scope scans, so this method matches their approach: it walks
        `FirestoreGraphStore.all_current_nodes` rather than inventing a new
        scanning path. Deterministic result order (seeded-data insertion/
        Firestore read order) — callers requiring a specific order (e.g.
        `solvers.calibration_stats.rank_by_absolute_variance`'s tie-
        breaking) sort explicitly rather than relying on this method's
        order.
        """
        return tuple(
            outcome
            for outcome in self._store.all_current_nodes((Outcome,))
            if tag in outcome.attribution_tags
        )

    # -- dependency_chain (Phase 4 addition, NOT one of the 14 spec §5.7 ops) --

    def dependency_chain(
        self, obligation_id: NodeId, *, max_depth: int = _MAX_DEPENDENCY_CHAIN_DEPTH
    ) -> tuple[Obligation, ...]:
        """Directed transitive closure of `obligation_id`'s DEPENDS_ON
        prerequisites — the primitive spec §7.3 Stage 4's "must-start-by
        computed backwards through dependencies" needs (PHASES.md Phase 4,
        E1 work item 3).

        **Not part of `contracts.repositories.GraphReader`.** `neighbours`
        is deliberately bidirectional (its own docstring: "returns the
        node at the *other* end of every edge_type edge touching node_id,
        regardless of which end node_id sits at") — correct for most of
        spec §5.7's examples, but it cannot alone distinguish "obligations
        this one depends on" from "obligations that depend on this one."
        Nothing else in the 14-method Protocol exposes directed edges for
        an arbitrary edge type the way `conflicts()` does for exactly
        CONFLICTS_WITH/VIOLATES. Rather than editing `contracts/
        repositories.py` (frozen, CTO-owned) to add a Protocol method
        myself, this is a concrete-only addition: a working reference
        implementation, reachable by E1's own callers, and the basis for a
        Protocol-addition recommendation reported back to the CTO/E2.
        Callers holding only the `GraphReader` Protocol type cannot call
        this — that limitation is real and is called out in this phase's
        report, not hidden.

        Follows `Edge.from_id -> Edge.to_id` only (`depends_on`: OBLIGATION
        -> OBLIGATION per spec §5.3 — the *from* side is the dependent
        obligation, the *to* side is its prerequisite). Cycle-safe: a node
        already discovered is never re-queued. BFS discovery order.
        """
        adjacency: dict[NodeId, list[NodeId]] = {}
        for edge in self._store.all_edges():
            if edge.edge_type is EdgeType.DEPENDS_ON:
                adjacency.setdefault(edge.from_id, []).append(edge.to_id)

        seen = {obligation_id}
        frontier = [obligation_id]
        discovered_ids: list[NodeId] = []
        depth = 0
        while frontier and depth < max_depth:
            next_frontier: list[NodeId] = []
            for node_id in frontier:
                for prerequisite_id in adjacency.get(node_id, ()):
                    if prerequisite_id in seen:
                        continue
                    seen.add(prerequisite_id)
                    discovered_ids.append(prerequisite_id)
                    next_frontier.append(prerequisite_id)
            frontier = next_frontier
            depth += 1

        obligations: list[Obligation] = []
        for node_id in discovered_ids:
            node = self._store.get_node(node_id)
            if isinstance(node, Obligation):
                obligations.append(node)
        return tuple(obligations)

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
        Allocator input, and Phase 4's load-conflict pre-pass primitive —
        PHASES.md Phase 4, E1 work item 2): total `effort_estimate_minutes`
        across obligations `owned_by` this person, due within `window`.

        Hardened in Phase 4 to exclude closed-status obligations
        (`CLOSED_OBLIGATION_STATUSES`: completed, dropped, superseded) —
        without this, a superseded obligation's old version would double-
        count against a person's load alongside its replacement, and a
        dropped (explicitly abandoned) obligation would count against a
        person's fairness threshold despite no longer being real work. This
        matches the "open obligations" convention `FirestoreObligation
        Repository.open_obligations_for` already established in Phase 1."""
        start, end = window
        total_minutes = 0.0
        for edge in self._store.edges_to(person_id, EdgeType.OWNED_BY):
            obligation = self._store.get_node(edge.from_id)
            if not isinstance(obligation, Obligation):
                continue
            if obligation.status in CLOSED_OBLIGATION_STATUSES:
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
