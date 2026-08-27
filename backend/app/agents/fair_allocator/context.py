"""Real-graph assembly for the Fair Allocator (A17-A21, spec §8, PHASES.md
Phase 8) — the "read via GraphReader" side of A18's observed-history input
and A21's household-aggregate load input, kept separate from each agent's
own pure reasoning logic (hexagonal architecture: an agent's core logic
never imports `contracts.repositories.GraphReader` machinery directly for
this kind of multi-hop assembly; mirrors `app.agents.consequence.context`'s
established role for A12-A16 exactly, one phase later).
"""

from __future__ import annotations

from datetime import datetime

from contracts.graph_types import EdgeType, NodeId, Obligation
from contracts.repositories import GraphReader

from .types import ObservedEffortSignal


def resolve_observed_effort_signals(
    reader: GraphReader, *, person_id: NodeId, window: tuple[datetime, datetime]
) -> tuple[ObservedEffortSignal, ...]:
    """Real, task-linked observed-completion evidence for one person over
    `window` — spec §8.3.2's "observed completion history" input, and the
    concrete answer to E1's Phase 8 final-report finding: correlating a
    `PurchaseItem` to a specific task needs a second hop.
    `GraphReader.effort_evidence` alone names *who* did *something*;
    `neighbours(item.id, EdgeType.DISCHARGES)` (already a working
    primitive, per E1's own confirmation this phase) is the second hop
    that names *which task* it was.

    A `PurchaseItem` with no `DISCHARGES` edge to any `Obligation` is real
    evidence of effort but not attributable to a specific task in this
    household's obligation graph — it is silently excluded here (never
    guessed at which task it might discharge); a genuinely uncorrelated
    purchase item is simply not usable as per-task valuation evidence for
    A18.

    Args:
        reader: the household's `GraphReader`.
        person_id: whose observed effort to resolve.
        window: the time window to resolve it over.

    Returns:
        One `ObservedEffortSignal` per (purchase item, discharged
        obligation) pair found — a single purchase item that discharges
        more than one obligation produces more than one signal, each
        correctly attributed.
    """
    signals: list[ObservedEffortSignal] = []
    for item in reader.effort_evidence(person_id, window):
        for neighbour in reader.neighbours(item.id, EdgeType.DISCHARGES):
            if not isinstance(neighbour, Obligation):
                continue
            signals.append(
                ObservedEffortSignal(
                    task_id=neighbour.id, purchase_item_id=item.id, description=item.description
                )
            )
    return tuple(signals)


def household_total_load(
    reader: GraphReader, *, person_ids: tuple[NodeId, ...], window: tuple[datetime, datetime]
) -> dict[NodeId, float]:
    """Real per-person observed obligation load for every person in
    `person_ids` over `window`, via `GraphReader.load` — a thin, real
    graph read per person. The caller (A21, or whoever assembles a
    `types.LoadDriftCheckRequest`) sums these itself to get the household
    total, so a caller that already has some persons' loads cached can mix
    real reads with cached values freely rather than being forced through
    one all-or-nothing aggregate call.
    """
    return {person_id: reader.load(person_id, window) for person_id in person_ids}


__all__ = ["household_total_load", "resolve_observed_effort_signals"]
