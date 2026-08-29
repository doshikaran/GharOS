"""`ScopedGraphReader` — a real, registration-level restriction on which
subgraph a Household Council domain specialist (A42-A46, spec §15.9) can
read, not a naming convention specialists are merely expected to honour
(PHASES.md Phase 12, E1 work item 1; ADR-019 Decision 1).

**Replaces E2's stopgap.** A first version of this exact file existed
under this same path, authored by E2, so Phase 12's Council specialists
(`backend/app/agents/council/`) could type-check and be tested before
E1's own authoritative version landed — its own docstring named this and
asked for a straight overwrite once this one existed. Checked directly
before replacing it: nothing outside `backend/app/graph/` constructs
`OutOfScopeGraphAccess` directly or reads its `.operation`/`scope_name`
attributes, and nothing outside this file's own `conformance.py` neighbour
constructs a `ScopedGraphReader` — so this replacement is exactly the
"safe, silent swap" that stopgap's own docstring predicted, with one
real, deliberate correction: this version's `OutOfScopeGraphAccess`
constructor keyword is `method` (`scope_name`, `method`), matching this
phase's own frozen brief verbatim (`def __init__(self, *, scope_name:
str, method: str) -> None: ...`) rather than the stopgap's `operation`.

`contracts/repositories.py`'s `GraphReader` Protocol has carried this line
since Phase 1: "Council specialists (A42-A46) each get a `GraphReader`
restricted to their own domain subgraph ... mutually distinct T0 scopes is
a registration-level constraint, tested, not a convention." Checked
directly at the start of this phase: no such mechanism existed anywhere in
this codebase before this module. This is that mechanism.

## Why a predicate over `object`, not a `NodeType` enum switch

This codebase's 18 node types are plain, `isinstance`-distinguished
dataclasses — there is no `NodeType` string enum anywhere to switch over.
A `GraphSubgraphScope.node_predicate` is therefore an `isinstance` check,
occasionally refined by a node's own field (`Constraint.kind`, the only
node type genuinely shared across more than one of the five scopes below)
— never a type-tag comparison, because no such tag exists to compare
(ADR-019 Decision 1).

## Deny-by-default, allow-list explicit (ADR-019 Decision 1)

Every `GraphReader` Protocol method that can return domain-relevant
objects (`get_node`, `neighbours`, `blast_radius`, `blast_radius_multi`,
`history`, `outcome_variance`, `effort_evidence` — the **filtered**
methods) silently excludes whatever the scope's predicate rejects; every
other Protocol method (`path`, `conflicts`, `dependency_chain`, `load`,
`series`, `decisions_touching`, `concession_ledger`, `unexplained`,
`unverified`, `expected_but_absent`, `spend_by_category` — the **denied**
methods) raises `OutOfScopeGraphAccess` unconditionally, before ever
touching the wrapped reader. This matches the fail-closed posture this
project has used consistently (Phase 5's expiry-never-auto-approves,
Phase 10's conservative disclosability heuristic): a domain specialist has
no real business calling a household-wide/audit-oriented query at all, so
those methods are refused outright rather than filtered down to an
(often-empty, and therefore misleadingly "correct-looking") result.

**A filtered method is never an error path.** A Care specialist calling
`history(some_ledger_event_id)` gets back whatever `Outcome` nodes the
wrapped reader finds, filtered through Care's own predicate — which never
matches an `Outcome` (no scope below claims that node type), so the
result is legitimately always `()`. That is correct, filtered behaviour,
not a broken implementation: this module's contract is "never raise just
because *some* — or even *all* — results were filtered out" for every one
of the seven filtered methods. Only the eleven denied methods ever raise.

## `dependency_chain` — already a real Protocol method, not the "concrete-
## only addition" its own docstring (and this phase's own brief) describe

`backend/app/graph/reader.py`'s `FirestoreGraphReader.dependency_chain`
docstring states it is "not part of `contracts.repositories.GraphReader`"
and this phase's own work order names it as "reachable on a concrete
`FirestoreGraphReader`" but "not part of the formal Protocol." Checked
directly against `contracts/repositories.py` while building this module:
`dependency_chain` **is** declared on the `GraphReader` Protocol (between
`conflicts` and `load`), with its own docstring dating the promotion to
Phase 4. Both of those other documents are stale, not this module —
`dependency_chain` is implemented here as an ordinary Protocol method
(denied, like the other ten), not as a defensive extra. Flagged for the
CTO/E1's own Phase 12 report rather than silently corrected in either of
those two other files (out of this module's ownership to fix their prose;
their behaviour was already correct either way, since both described
outcomes — "deny it, Protocol member or not" — coincide).

## `Person` visibility under `CARE_SCOPE` — "capability-flag reads only"
## is a usage convention, not a field-level redaction

ADR-019 describes Care's `Person` access as "capability flags only
(`has_medical_proxy`, mobility-relevant fields)". Nothing in this
codebase's `GraphReader` Protocol shape supports returning a partial,
field-redacted node — every method returns the real, fully-typed
dataclass instance or nothing at all, and `Person` is `frozen=True`
(constructing a redacted copy would itself require fabricating values for
whichever fields are dropped, which no clean subset of `Person`'s fields
badly needs to be a value it never held). `CARE_SCOPE.node_predicate`
therefore admits any `Person` node in full; "capability-flag reads only"
is honoured as a usage discipline for A43 Care (spec §15.9's own tool
note: "constraint read only" — Care queries capability flags, it is never
handed a reason to read anything else on the node), not as a runtime
filter this wrapper enforces field-by-field. This is a documented,
deliberate scope decision, not a gap.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import NoReturn

from contracts.graph_types import (
    Constraint,
    ConstraintKind,
    Decision,
    Edge,
    EdgeType,
    LedgerEvent,
    NodeId,
    Obligation,
    Outcome,
    Person,
    PurchaseItem,
    RecurringCommitment,
    SourceDocument,
)
from contracts.repositories import GraphReader


class OutOfScopeGraphAccess(Exception):
    """Raised by a `ScopedGraphReader` method a specialist has no real
    business calling, or when a returned node doesn't match its scope.

    In this module's own concrete implementation, only the first reason
    is ever actually exercised: every one of `ScopedGraphReader`'s eleven
    *denied* methods raises this unconditionally (ADR-019 Decision 1's
    deny-by-default posture), while every one of its seven *filtered*
    methods (`get_node`, `neighbours`, `blast_radius`,
    `blast_radius_multi`, `history`, `outcome_variance`,
    `effort_evidence`) never raises this for an out-of-scope result — it
    silently excludes it instead (`None` for `get_node`, an absent element
    for every tuple-returning filtered method). The second reason named in
    this docstring is carried for a caller that needs to *assert* a
    specific already-known node matches a scope (rather than have a
    mismatch silently disappear) and chooses to raise this same exception
    type to do it; no method on this module's own `ScopedGraphReader`
    currently does that itself.
    """

    def __init__(self, *, scope_name: str, method: str) -> None:
        self.scope_name = scope_name
        self.method = method
        super().__init__(
            f"scope {scope_name!r} has no access to GraphReader.{method}() — "
            "ADR-019 deny-by-default: a Council domain specialist only ever reads its own subgraph"
        )


@dataclass(frozen=True, slots=True)
class GraphSubgraphScope:
    """One Council domain specialist's real, registration-level T0 read
    scope (ADR-019 Decision 1). `node_predicate` decides, for any node
    object a wrapped `GraphReader` might return, whether it belongs to
    this scope."""

    name: str
    node_predicate: Callable[[object], bool]


_CARE_CONSTRAINT_KINDS = frozenset({ConstraintKind.MEDICAL, ConstraintKind.MOBILITY})
_LEGAL_CONSTRAINT_KINDS = frozenset({ConstraintKind.LEGAL, ConstraintKind.CUSTODY})


def _finance_predicate(node: object) -> bool:
    """A42 Finance: "queries the Ledger subgraph" (spec §15.9) —
    `LedgerEvent`, `RecurringCommitment`."""
    return isinstance(node, LedgerEvent | RecurringCommitment)


def _care_predicate(node: object) -> bool:
    """A43 Care: "queries the constraint/medical subgraph" (spec §15.9) —
    `Constraint` where `kind in {MEDICAL, MOBILITY}`; `Person` in full
    (see this module's docstring on why "capability-flag reads only" is a
    usage convention, not a field-level filter)."""
    if isinstance(node, Person):
        return True
    return isinstance(node, Constraint) and node.kind in _CARE_CONSTRAINT_KINDS


def _education_predicate(node: object) -> bool:
    """A44 Education: "queries the education subgraph: exam years,
    admission cycles, transfer windows, catchment" (spec §15.9) —
    `Constraint` where `kind == EDUCATION` (ADR-019 Decision 2, this
    phase's new `ConstraintKind` member)."""
    return isinstance(node, Constraint) and node.kind is ConstraintKind.EDUCATION


def _logistics_predicate(node: object) -> bool:
    """A45 Logistics: "queries the obligation subgraph: real recurring
    trips, distances, capacity requirements, parking" (spec §15.9) —
    `Obligation` unfiltered; `Constraint` where `kind == SCHEDULE`."""
    if isinstance(node, Obligation):
        return True
    return isinstance(node, Constraint) and node.kind is ConstraintKind.SCHEDULE


def _legal_predicate(node: object) -> bool:
    """A46 Legal/Compliance: "documentation, society rules, regulatory
    requirements" (spec §15.9) — `Constraint` where
    `kind in {LEGAL, CUSTODY}`; `SourceDocument`."""
    if isinstance(node, SourceDocument):
        return True
    return isinstance(node, Constraint) and node.kind in _LEGAL_CONSTRAINT_KINDS


FINANCE_SCOPE = GraphSubgraphScope(name="finance", node_predicate=_finance_predicate)
CARE_SCOPE = GraphSubgraphScope(name="care", node_predicate=_care_predicate)
EDUCATION_SCOPE = GraphSubgraphScope(name="education", node_predicate=_education_predicate)
LOGISTICS_SCOPE = GraphSubgraphScope(name="logistics", node_predicate=_logistics_predicate)
LEGAL_SCOPE = GraphSubgraphScope(name="legal", node_predicate=_legal_predicate)
"""The five frozen scope constants, one per Council domain specialist
(A42-A46) — fully disjoint by construction (`test_scoped_graph_reader.py`
proves this pairwise, by construction, not by eyeball): no real node can
ever satisfy two of these five predicates, because the node types each
scope claims outright (`LedgerEvent`/`RecurringCommitment` vs `Person` vs
`Obligation` vs `SourceDocument`) never overlap with each other, and the
one node type more than one scope touches (`Constraint`) is partitioned by
its own `kind` field into four disjoint sets
(`{MEDICAL, MOBILITY}` / `{EDUCATION}` / `{SCHEDULE}` / `{LEGAL, CUSTODY}`)
that never share a member. This is stronger than spec §12.2's own minimum
bar ("no two agents share both tool access *and* objective," which
tolerates partial subgraph overlap as long as objectives differ) —
disjointness was reachable here without contortion, so Gate 12's own "if
two specialists were swapped, would output change?" review question is
trivially, structurally true rather than an empirical hope (ADR-019)."""


class ScopedGraphReader:
    """Wraps a real `GraphReader` (any concrete implementation — the
    Firestore-backed one in production, a fake in a unit test) and
    restricts every read to one `GraphSubgraphScope`. Structurally
    satisfies `contracts.repositories.GraphReader` itself (same method
    names and signatures — see `app.graph.conformance` for the
    mypy-checked structural proof), so a `ScopedGraphReader` substitutes
    directly for an unscoped reader wherever Council specialist
    construction code expects one.
    """

    def __init__(self, *, reader: GraphReader, scope: GraphSubgraphScope) -> None:
        self._reader = reader
        self._scope = scope

    # -- filtered methods (silently exclude out-of-scope results) ----------

    def get_node(self, node_id: NodeId) -> object | None:
        node = self._reader.get_node(node_id)
        if node is None or not self._scope.node_predicate(node):
            return None
        return node

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        return self._filtered(self._reader.neighbours(node_id, edge_type))

    def blast_radius(self, node_id: NodeId, depth: int) -> tuple[object, ...]:
        return self._filtered(self._reader.blast_radius(node_id, depth))

    def blast_radius_multi(self, node_ids: tuple[NodeId, ...], depth: int) -> tuple[object, ...]:
        return self._filtered(self._reader.blast_radius_multi(node_ids, depth))

    def history(self, entity_id: NodeId) -> tuple[Outcome, ...]:
        return tuple(o for o in self._reader.history(entity_id) if self._scope.node_predicate(o))

    def outcome_variance(self, tag: str) -> tuple[Outcome, ...]:
        return tuple(o for o in self._reader.outcome_variance(tag) if self._scope.node_predicate(o))

    def effort_evidence(
        self, person_id: NodeId, window: tuple[datetime, datetime]
    ) -> tuple[PurchaseItem, ...]:
        return tuple(
            i for i in self._reader.effort_evidence(person_id, window) if self._scope.node_predicate(i)
        )

    def _filtered(self, nodes: tuple[object, ...]) -> tuple[object, ...]:
        return tuple(n for n in nodes if self._scope.node_predicate(n))

    # -- denied methods (raise unconditionally, never touch self._reader) --

    def _deny(self, method: str) -> NoReturn:
        raise OutOfScopeGraphAccess(scope_name=self._scope.name, method=method)

    def path(self, from_id: NodeId, to_id: NodeId) -> tuple[Edge, ...]:
        self._deny("path")

    def conflicts(self, scope: str) -> tuple[Edge, ...]:
        self._deny("conflicts")

    def dependency_chain(self, obligation_id: NodeId, *, max_depth: int = 25) -> tuple[Obligation, ...]:
        """Already a real `GraphReader` Protocol method (see this module's
        own docstring) — denied here like every other non-filtered method,
        not a defensive extra."""
        self._deny("dependency_chain")

    def load(self, person_id: NodeId, window: tuple[datetime, datetime]) -> float:
        self._deny("load")

    def series(self, commitment_id: NodeId) -> tuple[object, ...]:
        self._deny("series")

    def decisions_touching(self, entity_id: NodeId) -> tuple[Decision, ...]:
        self._deny("decisions_touching")

    def concession_ledger(self, person_id: NodeId) -> tuple[Decision, ...]:
        self._deny("concession_ledger")

    def unexplained(self, scope: str) -> tuple[NodeId, ...]:
        self._deny("unexplained")

    def unverified(self, scope: str) -> tuple[NodeId, ...]:
        self._deny("unverified")

    def expected_but_absent(self, constraint_id: NodeId) -> tuple[NodeId, ...]:
        self._deny("expected_but_absent")

    def spend_by_category(self, window: tuple[datetime, datetime]) -> dict[str, float]:
        self._deny("spend_by_category")


__all__ = [
    "CARE_SCOPE",
    "EDUCATION_SCOPE",
    "FINANCE_SCOPE",
    "LEGAL_SCOPE",
    "LOGISTICS_SCOPE",
    "GraphSubgraphScope",
    "OutOfScopeGraphAccess",
    "ScopedGraphReader",
]
