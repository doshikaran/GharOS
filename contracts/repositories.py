"""GharOS — frozen repository protocols.

Owned exclusively by the CTO. Abstract protocols only — **no Firestore
types leak in** (PHASES.md Phase 0.A). Concrete implementations live in
`backend/app/persistence/` and `backend/app/graph/` (E1). Every reasoning
agent (E2) and every tool (E3) accesses the graph exclusively through these
protocols — never through a database client directly (Repository pattern,
PHASES.md §2.2).
"""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from contracts.graph_types import (
    Branch,
    CouncilPosition,
    Decision,
    Edge,
    EdgeType,
    NodeId,
    Obligation,
    Outcome,
    Pattern,
    Person,
    PurchaseItem,
)


class GraphReader(Protocol):
    """T0 — read-only graph access. Subgraph-scoped per caller: e.g. the
    Reconciliation Agent (A28) is wired to a GraphReader restricted to the
    Ledger subgraph; Council specialists (A42-A46) each get a GraphReader
    restricted to their own domain subgraph (spec §12.2 — mutually
    distinct T0 scopes is a registration-level constraint, tested, not a
    convention)."""

    def get_node(self, node_id: NodeId) -> object | None:
        """Returns the typed node (one of contracts.graph_types' node
        dataclasses) or None if absent/superseded."""
        ...

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        """spec §5.7 — e.g. obligations owned by a person."""
        ...

    def path(self, from_id: NodeId, to_id: NodeId) -> tuple[Edge, ...]:
        """spec §5.7 — Path Explainer's (A9) core capability: why does this
        email affect Tuesday's lunch? Returns the walked edge chain, empty
        tuple if no path exists."""
        ...

    def blast_radius(self, node_id: NodeId, depth: int) -> tuple[object, ...]:
        """spec §5.7 — what breaks if we relocate in June? Used by the
        Simulator and Council."""
        ...

    def conflicts(self, scope: str) -> tuple[Edge, ...]:
        """spec §5.7 — all unresolved conflicts_with/violates edges in scope."""
        ...

    def load(self, person_id: NodeId, window: tuple[datetime, datetime]) -> float:
        """spec §5.7 — a person's obligation load in a time window, used
        by the Fair Allocator."""
        ...

    def series(self, commitment_id: NodeId) -> tuple[object, ...]:
        """spec §5.7 — all LEDGER_EVENTs belonging to a RECURRING_COMMITMENT."""
        ...

    def history(self, entity_id: NodeId) -> tuple[Outcome, ...]:
        """spec §5.7 — all OUTCOMEs for a given entity, used by Calibration."""
        ...

    def decisions_touching(self, entity_id: NodeId) -> tuple[Decision, ...]:
        """spec §5.7 — every past DECISION involving a given entity."""
        ...

    def concession_ledger(self, person_id: NodeId) -> tuple[Decision, ...]:
        """spec §5.7 — DECISIONs where this person has a `conceded_by` edge,
        for fairness-over-time tracking."""
        ...

    def unexplained(self, scope: str) -> tuple[NodeId, ...]:
        """spec §5.7 — nodes lacking provenance. MUST be empty on any
        correctly-written graph; used as an audit/integrity check, not a
        normal query path."""
        ...

    def unverified(self, scope: str) -> tuple[NodeId, ...]:
        """spec §5.7 — graph claims with no real-world verification evidence
        (no `verifies` edge) behind them."""
        ...

    def expected_but_absent(self, constraint_id: NodeId) -> tuple[NodeId, ...]:
        """spec §5.7 — SOURCE_DOCUMENTs where expected evidence for a
        constraint never appeared; backs the `absent_from` edge and the
        Pattern Miner's silent-non-compliance signal (spec §5.5)."""
        ...

    def spend_by_category(self, window: tuple[datetime, datetime]) -> dict[str, float]:
        """spec §5.7 — real spend from PURCHASE_ITEM line items, not
        estimates."""
        ...

    def effort_evidence(self, person_id: NodeId, window: tuple[datetime, datetime]) -> tuple[PurchaseItem, ...]:
        """spec §5.7 — who actually did the runs, from `evidences_effort`
        edges; a primary Fair Allocator input (spec §5.5)."""
        ...


class GraphWriter(Protocol):
    """T3 — internal graph writes. Writer agents only (A7 Graph Builder,
    A15 Obligation Writer, A49 Council Recorder, etc.) — never a reasoning
    agent writing directly.

    **The provenance guard is the contract, not an implementation detail:**
    every method here MUST raise contracts.errors.ProvenanceMissing if the
    node/edge's Provenance is incomplete. This must be structurally
    impossible to bypass (PHASES.md Phase 1, Gate 1: proven by a hypothesis
    fuzz test)."""

    def write_node(self, node: object) -> NodeId:
        """Writes a new node or a new version of an existing one (writes
        create versions; they never mutate in place — PHASES.md §2.2)."""
        ...

    def write_edge(self, edge: Edge) -> None: ...

    def supersede_node(self, old_node_id: NodeId, new_node: object) -> NodeId:
        """Sets `superseded_at` on the old node's Provenance and writes the
        new version. `superseded_at` is set, never overwritten."""
        ...


class PersonRepository(Protocol):
    def get(self, person_id: NodeId) -> Person | None: ...
    def find_by_alias(self, alias: str) -> tuple[Person, ...]: ...


class ObligationRepository(Protocol):
    def get(self, obligation_id: NodeId) -> Obligation | None: ...
    def open_obligations_for(self, person_id: NodeId) -> tuple[Obligation, ...]: ...
    def unassigned(self) -> tuple[Obligation, ...]: ...


class DecisionRepository(Protocol):
    """DECISION, BRANCH, and COUNCIL_POSITION records — permanent, never
    pruned (spec §5.2, §20)."""

    def get_decision(self, decision_id: NodeId) -> Decision | None: ...
    def branches_for(self, decision_id: NodeId) -> tuple[Branch, ...]: ...
    def positions_for(self, decision_id: NodeId) -> tuple[CouncilPosition, ...]: ...


class PatternRepository(Protocol):
    """Written only by the Pattern Miner (A10), scheduled and support-
    threshold gated (spec §15.3)."""

    def all_patterns(self) -> tuple[Pattern, ...]: ...
    def write_pattern(self, pattern: Pattern) -> NodeId: ...


class AuditLog(Protocol):
    """L6 — immutable, append-only (spec §6.2). `write_before_execute` in
    `backend/app/audit/` (E1) wraps this so that safety invariant #2 (audit
    before execute) is structural rather than a documentation promise."""

    def append(self, *, action_type: str, payload: dict[str, str], occurred_at: datetime) -> str:
        """Returns the AuditRecord id. Must be called and durably persisted
        BEFORE the corresponding action executes — never after."""
        ...


class IdempotencyStore(Protocol):
    """Backs contracts.actions.IdempotencyKey. A replay with an identical
    key and identical intended effect returns the original result as a
    no-op; a replay with the same key but a different effect raises
    contracts.errors.IdempotencyConflict."""

    def check_and_reserve(self, key: str) -> str | None:
        """Returns the prior result reference if this key was already
        used, or None if this is the first use (caller should proceed and
        then call `record_result`)."""
        ...

    def record_result(self, key: str, result_ref: str) -> None: ...


class GraphIntegrityChecker(Protocol):
    """Deterministic tool (not an LLM) — orphans, missing provenance,
    dangling edges (spec §16.2, PHASES.md Phase 1 work item 7)."""

    def check(self, scope: str) -> tuple[str, ...]:
        """Returns a tuple of human-readable integrity violations. Empty
        tuple = clean."""
        ...
