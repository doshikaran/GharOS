"""A11 — Graph Maintainer (spec §15.2, §20; PHASES.md Phase 14; ADR-021
Decision 2).

Scheduled, **deterministic** — no model call anywhere in this module, and
`"A11"` is deliberately absent from `app.reasoning.model_router.
PRO_TIER_ALLOWLIST` (same status as A15 Obligation Writer, A49 Council
Recorder). Three responsibilities, each reusing existing machinery rather
than reinventing it:

1. **Supersession** — `supersede()` below is a thin, tested delegation to
   the already-correct, already-guarded `contracts.repositories.
   GraphWriter.supersede_node` (Phase 1). Nothing new to build; this
   wrapper exists only so A11's own call path is a real, exercised part
   of this module rather than an unexercised assumption.

2. **Staleness marking** — `flagged_for_review()` reuses `app.solvers.
   staleness.is_stale` (the shared rule extracted from Phase 9's A22
   Intention Capture agent — see that module's docstring for the
   duplication note) at graph-wide, scheduled scope, over every current
   `Obligation` in the store.

   **Why this returns a live, computed value rather than writing anything
   to the graph:** the two `contracts/graph_types.py` shapes ADR-021
   floated as reuse candidates for a persisted "flagged" marker —
   overloading `Obligation.status` or writing a `Pattern`-shaped review
   note — were checked against the real contract and rejected. Overloading
   `ObligationStatus` (`DERIVED`/`ASSIGNED`/`PREPARED`/`IN_PROGRESS`/
   `COMPLETED`/`DROPPED`/`SUPERSEDED`) with a meaning like "stale" would
   be lossy and misleading (a stale obligation is not dropped, completed,
   or superseded — it is still exactly whatever status it already had,
   just old) and is a `contracts/` decision E1 cannot make unilaterally.
   Writing a `Pattern` node per stale obligation would need either a
   growing, never-cleared log (a obligation that stops being stale is
   never un-flagged — there is no delete/status primitive on `Pattern`
   either) or reusing `Pattern.contributing_outcome_ids` to hold an
   `Obligation` id, silently changing what that field is documented to
   mean for every other consumer of `Pattern` nodes. Both are real, new
   contract-adjacent commitments in disguise — exactly what ADR-021's
   "zero new contracts" decision and this phase's "escalate to the CTO
   rather than editing `contracts/` yourself" instruction guard against.

   Instead, `flagged_for_review()` is a `app.solvers`-style deterministic
   query (like `calibration_stats.compute_calibration`): it recomputes the
   real, current answer directly from graph state on every call, via
   `FirestoreGraphStore.all_current_nodes((Obligation,))` (this module is
   E1's own concrete, Firestore-aware maintenance job — like
   `FirestoreGraphIntegrityChecker` before it, it is allowed to depend on
   `FirestoreGraphStore` directly rather than only the narrower
   `contracts.repositories` Protocols, which exist to keep *other roles'*
   code, e.g. E2's reasoning agents, off a database client, per
   gharos-standards). This is genuinely "real and queryable" — any caller
   (the Consolidation Service, a debug endpoint, a future UI) gets the
   honest, current set of flagged obligations, with no separate persisted
   state that can drift from the truth or accumulate unboundedly.

3. **Orphan/integrity** — `check_integrity()` runs the existing
   `contracts.repositories.GraphIntegrityChecker.check()`
   (`FirestoreGraphIntegrityChecker`, Phase 1) and returns its violations
   unchanged. This module does not reimplement orphan detection.

**The safety-critical piece — protected node types are never pruned,
structurally:** see `assert_prunable`/`ProtectedNodeError`/
`prune_if_eligible` below.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.graph_types import Constraint, ConstraintSeverity, Decision, NodeId, Obligation, Outcome
from contracts.repositories import GraphIntegrityChecker, GraphWriter

from app.persistence.firestore_store import FirestoreGraphStore
from app.solvers.staleness import StalenessCheck, is_stale

logger = structlog.get_logger(__name__)


class ProtectedNodeError(RuntimeError):
    """Raised by `assert_prunable` when a caller attempts to prune/delete
    a node from one of the four categories spec §20 and PHASES.md Phase
    14 forbid pruning, **ever**: `DECISION` nodes, `OUTCOME` nodes, any
    node's own provenance record (every historical version of every
    node — see `assert_prunable`'s docstring), and any `Constraint` whose
    `severity` is `ConstraintSeverity.HARD`.

    Fail-closed by construction: this is raised, never returned as a
    boolean or logged-and-ignored, matching this project's consistent
    posture on safety-critical checks (Phase 5's expiry-never-
    auto-approves, Phase 12's deny-by-default `ScopedGraphReader`)."""


_PROTECTED_NODE_TYPES: tuple[type, ...] = (Decision, Outcome)
"""`DECISION` and `OUTCOME` — unconditionally protected regardless of any
field on the node itself. `Constraint` is protected conditionally (only
`severity == HARD`) so it is checked separately in `assert_prunable`,
not folded into this tuple."""


def assert_prunable(node: object) -> None:
    """The structural gate every deletion/pruning code path in this
    module — and any future one — MUST call before removing anything.
    Raises `ProtectedNodeError` for a protected node; returns `None`
    (silently, correctly) for anything else.

    **Checked directly against the real persistence layer before writing
    this function, per this phase's own instruction not to assume:**
    `app.persistence.firestore_store.FirestoreGraphStore` exposes exactly
    two write primitives, `put_node` and `supersede_node` (see that
    module) — there is **no delete/hard-remove primitive anywhere in this
    codebase, for any node type.** `supersede_node` never deletes: it
    sets `superseded_at` on the prior version and keeps that prior
    version, forever, as an immutable, still-readable version
    (`FirestoreGraphStore.supersede_node`'s own docstring; `node_history`
    proves every version is still retrievable). This means "any node's
    own provenance record" — i.e. every version of every node the graph
    has ever held — is *already*, structurally, never prunable by this
    codebase's only two write primitives, independent of this function
    ever being called. There is nothing this function needs to check for
    that category; it is guarded by the absence of a delete primitive,
    not by a runtime type check.

    What this function actually guards against is different: a
    **future** delete primitive. PHASES.md Phase 14's own scope note
    ("except where ... Graph Maintainer explicitly permits pruning of
    non-protected types") leaves room for a later phase to add real
    pruning for genuinely non-protected node types (e.g. a long-superseded
    `SourceDocument`'s raw payload blob past its audit-retention horizon).
    Adding such a primitive is a `contracts.repositories.GraphWriter`
    change — CTO-only, out of scope this phase, and this module adds
    none. `assert_prunable` is the load-bearing gate any such future
    primitive is REQUIRED to call before acting on `node`, so that when
    one is eventually added, it is already safe by construction rather
    than by remembering to add a check later.

    Args:
        node: any graph node object (a `contracts.graph_types` dataclass
            instance).

    Raises:
        ProtectedNodeError: `node` is a `Decision`, an `Outcome`, or a
            `Constraint` with `severity == ConstraintSeverity.HARD`.
    """
    if isinstance(node, _PROTECTED_NODE_TYPES):
        raise ProtectedNodeError(
            f"{type(node).__name__} nodes are never pruned (id={getattr(node, 'id', '?')})"
        )
    if isinstance(node, Constraint) and node.severity is ConstraintSeverity.HARD:
        raise ProtectedNodeError(f"HARD constraints are never pruned (id={node.id})")


@dataclass(frozen=True, slots=True)
class StalenessFlag:
    """One currently-stale `Obligation`, as computed live by
    `GraphMaintainer.flagged_for_review()` — not a persisted graph node
    (see this module's docstring for why)."""

    obligation_id: NodeId
    title: str
    reason: str
    days_stale: int
    threshold_days: int


@dataclass(frozen=True, slots=True)
class MaintenanceRunResult:
    """The real, structured output of one `GraphMaintainer.run()` — what
    the Consolidation Service logs as evidence of a genuine run (PHASES.md
    Phase 14, "genuine overnight run" evidence), not a bare success
    boolean."""

    ran_at: datetime
    obligations_flagged: tuple[StalenessFlag, ...]
    integrity_violations: tuple[str, ...]


class GraphMaintainer:
    """A11 Graph Maintainer. Dependency-injected on the real Firestore
    store (for the graph-wide obligation scan), a `GraphIntegrityChecker`
    (Protocol — normally `FirestoreGraphIntegrityChecker`), and a
    `GraphWriter` (Protocol — for the supersession call path)."""

    def __init__(
        self,
        *,
        store: FirestoreGraphStore,
        integrity_checker: GraphIntegrityChecker,
        graph_writer: GraphWriter,
    ) -> None:
        self._store = store
        self._integrity_checker = integrity_checker
        self._graph_writer = graph_writer

    def supersede(self, old_node_id: NodeId, new_node: object) -> NodeId:
        """A11's own supersession call path. Delegates entirely to
        `GraphWriter.supersede_node` — see this module's docstring,
        responsibility 1. `new_node` still passes through the real
        provenance guard inside the writer; this method adds no
        behaviour of its own.
        """
        return self._graph_writer.supersede_node(old_node_id, new_node)

    def prune_if_eligible(self, node: object) -> bool:
        """The single entry point any pruning capability in this module
        goes through — see `assert_prunable`'s docstring for why this is
        currently a guarded no-op rather than a real delete.

        The guard runs FIRST, unconditionally, before the (currently
        nonexistent) prune action — so a protected node raises even
        though "nothing would have happened anyway." This ordering
        matters: it is what keeps the guarantee alive once a real delete
        primitive is eventually added elsewhere and starts calling this
        same method.

        Returns:
            Always `False` today — there is no delete primitive in this
            codebase for this method to invoke on a non-protected node
            (see `assert_prunable`'s docstring). Never `True` until a
            real `contracts.repositories.GraphWriter` delete primitive
            exists and this method is deliberately wired to it.

        Raises:
            ProtectedNodeError: `node` is a `Decision`, `Outcome`, or
                HARD `Constraint`.
        """
        assert_prunable(node)
        logger.info(
            "graph_maintainer.prune_skipped_no_delete_primitive",
            node_type=type(node).__name__,
            node_id=str(getattr(node, "id", "?")),
        )
        return False

    def flagged_for_review(self, *, now: datetime | None = None) -> tuple[StalenessFlag, ...]:
        """Every currently-stale `Obligation` in the store, graph-wide —
        see this module's docstring, responsibility 2.

        Args:
            now: the reference time to check staleness against. Defaults
                to `datetime.now(UTC)` — injected so callers/tests can
                pin it.

        Returns:
            `StalenessFlag`s sorted by `obligation_id` ascending
            (deterministic output, independent of Firestore's stream
            ordering).
        """
        reference_time = now if now is not None else datetime.now(UTC)
        obligations = self._store.all_current_nodes((Obligation,))
        flags: list[StalenessFlag] = []
        for obligation in obligations:
            assert isinstance(obligation, Obligation)  # narrows for mypy; store is untyped `Any`
            check: StalenessCheck = is_stale(obligation, now=reference_time)
            if check.is_stale:
                flags.append(
                    StalenessFlag(
                        obligation_id=obligation.id,
                        title=obligation.title,
                        reason=check.reason,
                        days_stale=check.days_stale,
                        threshold_days=check.threshold_days,
                    )
                )
        flags.sort(key=lambda flag: str(flag.obligation_id))
        return tuple(flags)

    def check_integrity(self, scope: str = "all") -> tuple[str, ...]:
        """Runs the existing `GraphIntegrityChecker.check()` and returns
        its violations unchanged — see this module's docstring,
        responsibility 3."""
        return self._integrity_checker.check(scope)

    def run(self, *, now: datetime | None = None) -> MaintenanceRunResult:
        """One full A11 maintenance pass: staleness scan + integrity
        check. Called by the Consolidation Service (`app.graph.
        consolidation_service`) as the second step of every off-peak run.
        """
        reference_time = now if now is not None else datetime.now(UTC)
        flags = self.flagged_for_review(now=reference_time)
        violations = self.check_integrity("all")
        result = MaintenanceRunResult(
            ran_at=reference_time, obligations_flagged=flags, integrity_violations=violations
        )
        logger.info(
            "graph_maintainer.run_completed",
            ran_at=reference_time.isoformat(),
            obligations_flagged=len(flags),
            integrity_violations=len(violations),
        )
        return result


__all__ = [
    "GraphMaintainer",
    "MaintenanceRunResult",
    "ProtectedNodeError",
    "StalenessFlag",
    "assert_prunable",
]
