"""Real-graph assembly for the Household Simulator (A37, A38 — spec §11,
§15.8, PHASES.md Phase 11, ADR-017) — kept separate from each agent's own
pure reasoning logic (hexagonal architecture: mirrors `app.agents.
concierge.context`/`app.agents.fair_allocator.context`'s established role
for their own packages exactly, one phase later).

Two real, structural jobs live here:

1. `resolve_real_anchor_ids` — A37's "derive real anchor NodeIds from the
   graph" responsibility (PHASES.md Phase 11 work item): filters a
   caller-assembled candidate pool down to node ids that actually resolve
   to a real, still-current `Person`, `Obligation`, or `Constraint` —
   `GraphReader` has no "find every entity touching topic X" primitive
   (mirrors `app.agents.concierge.context`'s "no enumerate-all primitive,
   so the caller assembles the pool" precedent), so the caller supplies
   candidates and this function does the real existence/type check.
2. `summarize_anchor_nodes` — turns real blast-radius node objects into
   plain, human-readable summary strings for two real uses: (a) always
   included, verbatim, on `BranchProjection.projected_impacts` as a
   `"graph_blast_radius"` entry computed by code, never by the model
   (Gate 11: "every branch claim traceable to graph data" — this one
   entry is graph data by construction, not a model claim about it); (b)
   given to A38 as `CritiqueRequest.blast_radius_context` so its
   adversarial pass can check a projection's prose against the same real
   data A37 saw.
"""

from __future__ import annotations

from contracts.graph_types import Constraint, NodeId, Obligation, Person
from contracts.repositories import GraphReader

_SUMMARIZABLE_TYPES = (Person, Obligation, Constraint)


def resolve_real_anchor_ids(
    reader: GraphReader, *, candidate_ids: tuple[NodeId, ...]
) -> tuple[NodeId, ...]:
    """Filters `candidate_ids` down to ones that actually resolve to a
    real, currently-live `Person`, `Obligation`, or `Constraint` node —
    A37's real "derive real anchor NodeIds from the graph" step, never a
    blind pass-through of whatever the caller proposed.

    Args:
        reader: the household's `GraphReader`.
        candidate_ids: the caller-assembled candidate pool (people,
            obligations, constraints the caller believes touch this
            decision's topic) — may include stale, superseded, or
            entirely made-up ids; only real hits survive.

    Returns:
        The subset of `candidate_ids` that resolved to a real node of one
        of the three anchor-eligible types, in the same relative order,
        with duplicates removed. Never invents an id not in
        `candidate_ids`.
    """
    resolved: list[NodeId] = []
    seen: set[NodeId] = set()
    for candidate_id in candidate_ids:
        if candidate_id in seen:
            continue
        node = reader.get_node(candidate_id)
        if isinstance(node, _SUMMARIZABLE_TYPES):
            resolved.append(candidate_id)
            seen.add(candidate_id)
    return tuple(resolved)


def _summarize_one(node: object) -> str | None:
    if isinstance(node, Person):
        return f"Person({node.display_name}, role={node.role.value})"
    if isinstance(node, Obligation):
        due = node.due_at.isoformat() if node.due_at else "no due date on file"
        return f"Obligation({node.title!r}, type={node.obligation_type}, due={due})"
    if isinstance(node, Constraint):
        return (
            f"Constraint(kind={node.kind.value}, severity={node.severity.value}, "
            f'"{node.original_text}")'
        )
    return None


def summarize_anchor_nodes(nodes: tuple[object, ...]) -> tuple[str, ...]:
    """Real, human-readable summaries of blast-radius node objects — the
    graph-derived evidence backing `BranchProjection.projected_impacts`'s
    always-present `"graph_blast_radius"` entry and
    `CritiqueRequest.blast_radius_context`.

    Args:
        nodes: whatever `GraphReader.blast_radius_multi` returned —
            typed node dataclasses per `contracts.graph_types`, or, per
            that Protocol method's own `tuple[object, ...]` return type,
            possibly a node type this function does not know how to
            summarize.

    Returns:
        One summary string per summarizable node (`Person`, `Obligation`,
        `Constraint` — the three anchor-eligible types this phase's
        household decisions actually touch); a node of any other type is
        silently skipped, never rendered as a blank or malformed entry.
    """
    summaries: list[str] = []
    for node in nodes:
        summary = _summarize_one(node)
        if summary is not None:
            summaries.append(summary)
    return tuple(summaries)


__all__ = ["resolve_real_anchor_ids", "summarize_anchor_nodes"]
