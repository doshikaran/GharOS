"""Real-graph assembly shared by the Household Council specialists (A42-
A46 — spec §12, §15.9, PHASES.md Phase 12, ADR-019) — kept separate from
each specialist's own reasoning logic (hexagonal architecture: mirrors
`app.agents.simulator.context`'s established role for its own package one
phase earlier).

One real, structural job lives here: `resolve_scoped_related_nodes` reads
`DecisionFraming.candidate_branches[*].related_node_ids` through a
specialist's own `ScopedGraphReader` — the *same* real id list is handed
to every specialist (there is no per-specialist filtering the caller must
do), and each specialist's own scope naturally discloses only what that
scope can see (deny-by-default) — a Care-scope reader given a Finance-only
id resolves it to `None`, exactly as if the node did not exist at all.
This is what makes "no two specialists share both tools and objective"
checkable on real, shared input data (Gate 12's own "if two specialists
were swapped, would output change?" review question).
"""

from __future__ import annotations

from contracts.graph_types import (
    Constraint,
    LedgerEvent,
    NodeId,
    Obligation,
    Person,
    RecurringCommitment,
    SourceDocument,
)

from ...graph.scoped_reader import ScopedGraphReader
from .types import DecisionFraming

_SUMMARIZABLE_TYPES = (
    Person,
    Constraint,
    Obligation,
    LedgerEvent,
    RecurringCommitment,
    SourceDocument,
)


def resolve_scoped_related_nodes(
    reader: ScopedGraphReader, *, framing: DecisionFraming
) -> tuple[object, ...]:
    """Resolves every `related_node_ids` entry across `framing`'s candidate
    branches through `reader` — a `ScopedGraphReader` structurally
    discloses only nodes matching its own scope's predicate (deny-by-
    default; `ScopedGraphReader.get_node` returns `None` for anything
    outside scope), so this function never needs to know which ids
    "belong" to which specialist; the reader itself enforces that.

    Args:
        reader: this specialist's own, and only, `ScopedGraphReader`.
        framing: the decision's shared framing — the same
            `related_node_ids` pool every specialist receives.

    Returns:
        The subset of related node ids that resolved to a real, in-scope
        node, in stable order, with duplicates removed. Never invents a
        node not returned by `reader.get_node`.
    """
    resolved: list[object] = []
    seen: set[NodeId] = set()
    for branch in framing.candidate_branches:
        for node_id in branch.related_node_ids:
            if node_id in seen:
                continue
            seen.add(node_id)
            node = reader.get_node(node_id)
            if node is not None:
                resolved.append(node)
    return tuple(resolved)


def _summarize_one(node: object) -> str | None:
    if isinstance(node, Person):
        return f"Person({node.display_name}, role={node.role.value})"
    if isinstance(node, Constraint):
        return f'Constraint(kind={node.kind.value}, severity={node.severity.value}, "{node.original_text}")'
    if isinstance(node, Obligation):
        due = node.due_at.isoformat() if node.due_at else "no due date on file"
        return f"Obligation({node.title!r}, type={node.obligation_type}, due={due})"
    if isinstance(node, LedgerEvent):
        return (
            f"LedgerEvent(kind={node.kind.value}, amount={node.amount:.2f} {node.currency}, "
            f"counterparty={node.counterparty_raw!r}, occurred_at={node.occurred_at.isoformat()})"
        )
    if isinstance(node, RecurringCommitment):
        return (
            f"RecurringCommitment({node.label!r}, counterparty={node.counterparty!r}, "
            f"amount={node.amount:.2f}, cadence={node.cadence!r}, status={node.status})"
        )
    if isinstance(node, SourceDocument):
        return f"SourceDocument(channel={node.channel!r}, document_type={node.document_type!r})"
    return None


def summarize_scoped_nodes(nodes: tuple[object, ...]) -> tuple[str, ...]:
    """Real, human-readable summaries of resolved in-scope nodes — the
    evidence block every specialist's prompt is built from.

    Args:
        nodes: whatever `resolve_scoped_related_nodes` returned.

    Returns:
        One summary string per summarizable node; a node of any other
        type is silently skipped, never rendered as a blank entry.
    """
    summaries: list[str] = []
    for node in nodes:
        summary = _summarize_one(node)
        if summary is not None:
            summaries.append(summary)
    return tuple(summaries)


def branches_block(framing: DecisionFraming) -> str:
    """Formats `framing.candidate_branches` for a prompt — every
    specialist and the Adversary share this exact rendering so a real
    option's description is never paraphrased differently per agent."""
    if not framing.candidate_branches:
        return "(no candidate branches have been proposed yet)"
    lines = []
    for branch in framing.candidate_branches:
        lines.append(f"- [{branch.branch_id}] {branch.label}: {branch.description}")
    return "\n".join(lines)


__all__ = ["branches_block", "resolve_scoped_related_nodes", "summarize_scoped_nodes"]
