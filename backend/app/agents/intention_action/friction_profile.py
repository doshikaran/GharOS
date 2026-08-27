"""The friction-profile write path — ADR-015's `CHARACTERIZES` edge
(`PATTERN -> PERSON`) made real, per PHASES.md Gate 9's literal checklist
item: **"correction updates the friction profile."**

## Why this is a separate module, not part of `BlockerDiagnosisAgent`

Spec §15.9's A23 forbidden list is explicit: "unblocking... no search, no
draft, no write." A correction to a diagnosis is a genuinely new kind of
input (not unblocking), but the write it produces is still a real graph
write, and A23's module holds no `GraphWriter`, no `ToolRegistry`, no tool
import of any kind — deliberately, so "A23 never writes" is checkable by
grep, not just by review. Folding the friction-profile write into
`BlockerDiagnosisAgent` would mean either violating that (giving A23 a
write tool after all) or building a second, secretly-tool-bearing code
path inside the same module that the "no write" claim would then be
false about.

This module is the CTO-anticipated alternative named directly in this
phase's brief: "a small dedicated function/module." It is deterministic,
plain code — not an LLM agent, not a member of the 69-agent roster — that
takes a real `DiagnosisCorrection` (produced by whatever surfaces A23's
diagnosis to a human and receives their correction; out of this phase's
scope) and performs the real graph write. `Provenance.deriving_agent` on
every `Pattern`/`Edge` this module writes is still tagged `AgentId("A23")`
— not because this Python code executes A23's own class, but because
`deriving_agent` is a domain-ownership label throughout this codebase
(mirrors `app.agents.consequence.obligation_writer`'s `AGENT_ID = A15`
convention: shared graph-writing mechanics, attributed to the agent whose
domain judgment the write serves) — the friction profile is A23's
diagnostic domain learning from its own corrections, even though the
literal write happens in code A23's own class cannot reach.

## Real, versioned accumulation — never a fabricated first data point

`Pattern.support_count` increments with each real correction (or, in a
future phase, each real completion outcome) per ADR-015's own text:
"`support_count` incrementing as corrections and completions accumulate,
exactly matching `Pattern`'s existing design." A correction never
overwrites — writes create new versions (PHASES.md §2.2): an existing
matching `Pattern` is superseded by a new one with `support_count + 1`, a
fresh `SUPERSEDES` edge back to the prior version (mirrors `app.agents.
consequence.obligation_writer`'s exact supersession shape), and a fresh
`CHARACTERIZES` edge to the person (the prior `CHARACTERIZES` edge is left
in place, pointing at the now-superseded `Pattern` id — real history, not
erased).
"""

from __future__ import annotations

import re
import uuid

from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Pattern,
    Provenance,
)
from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore

from ...tools.graph_write_tool import GraphWriteTool
from .types import BlockerType, DiagnosisCorrection

_DERIVING_AGENT = AgentId("A23")
"""See module docstring — a domain-ownership label, not a claim that
`BlockerDiagnosisAgent`'s own code executed this write."""

_PATTERN_DESCRIPTION_PREFIX = "Friction pattern"
_DESCRIPTION_RE = re.compile(rf"^{re.escape(_PATTERN_DESCRIPTION_PREFIX)} \(([a-z_]+)\) — ")
"""Both human-readable (matches ADR-015's own worked example prose
exactly in spirit: "this person's dentist-type appointments are blocked
by aversion...") AND machine-parseable, by a documented, stable prefix
convention this module owns end-to-end as the only writer of `Pattern`
nodes reachable via `CHARACTERIZES`. `Pattern` carries no `structured`
dict (unlike `Constraint`) — this prefix is the real, defensible
alternative to inventing one."""

_BASE_CONFIDENCE = 0.5
_CONFIDENCE_PER_SUPPORT = 0.1
_MAX_CONFIDENCE = 0.9
"""A friction `Pattern`'s confidence grows with real accumulated
evidence, never starts near-certain from one correction, and never
reaches false certainty — mirrors `app.agents.fair_allocator.
valuation_extraction_agent._COST_CONFIDENCE_FLOOR`'s general discipline
of keeping confidence tied to real evidence volume, not asserted."""


def _pattern_confidence(support_count: int) -> float:
    return min(_BASE_CONFIDENCE + _CONFIDENCE_PER_SUPPORT * support_count, _MAX_CONFIDENCE)


def _pattern_description(*, blocker_type: BlockerType, person_display_name: str, detail: str) -> str:
    return f"{_PATTERN_DESCRIPTION_PREFIX} ({blocker_type.value}) — {person_display_name}: {detail}"


def extract_blocker_type_from_pattern(pattern: Pattern) -> BlockerType | None:
    """Recovers the `BlockerType` a friction `Pattern` was written for,
    from its own description — `None` for any `Pattern` not written by
    this module's convention (e.g. a Pattern Miner (A10) regularity
    unrelated to blocker diagnosis), never raises.
    """
    match = _DESCRIPTION_RE.match(pattern.description)
    if match is None:
        return None
    try:
        return BlockerType(match.group(1))
    except ValueError:
        return None


def find_matching_pattern(
    reader: GraphReader, *, person_id: NodeId, blocker_type: BlockerType
) -> Pattern | None:
    """The real, current friction `Pattern` for `person_id`/`blocker_type`,
    if one already exists — via `GraphReader.neighbours(person_id,
    EdgeType.CHARACTERIZES)`, the real ADR-015 query.
    """
    for node in reader.neighbours(person_id, EdgeType.CHARACTERIZES):
        if isinstance(node, Pattern) and extract_blocker_type_from_pattern(node) == blocker_type:
            return node
    return None


def summarise_for_person(reader: GraphReader, *, person_id: NodeId) -> str | None:
    """A real, plain-text summary of a person's entire friction profile
    (every real `Pattern` `CHARACTERIZES`-linked to them) — A23's
    `types.BlockerDiagnosisRequest.friction_profile_summary` input, built
    by whichever caller assembles that request. `None` when this person
    has no friction pattern on file at all yet.
    """
    patterns = [
        node for node in reader.neighbours(person_id, EdgeType.CHARACTERIZES) if isinstance(node, Pattern)
    ]
    if not patterns:
        return None
    lines = [f"- {pattern.description} (support: {pattern.support_count})" for pattern in patterns]
    return "\n".join(lines)


def apply_diagnosis_correction(
    *,
    reader: GraphReader,
    graph_writer: GraphWriter,
    idempotency_store: IdempotencyStore,
    correction: DiagnosisCorrection,
    person_display_name: str,
) -> NodeId:
    """Writes (or increments) the friction `Pattern` this correction is
    real evidence for, and connects it to the person via `CHARACTERIZES`.

    Args:
        reader: real `GraphReader`, used to find an existing matching
            `Pattern` (never assumed absent without checking).
        graph_writer: real `GraphWriter`, wrapped into a T3
            `GraphWriteTool` for provenance-enforced, idempotent writes.
        idempotency_store: backs the `GraphWriteTool`'s idempotency keys.
        correction: the real, human-issued correction.
        person_display_name: for the written `Pattern.description`'s
            human-readable half (see `_pattern_description`).

    Returns:
        The written (or newly-superseding) `Pattern`'s real `NodeId`.

    Raises:
        contracts.errors.ToolFailure: any underlying write failed.
        contracts.errors.ProvenanceMissing: propagates unchanged — see
            `GraphWriteTool.invoke_idempotent`'s own contract.
    """
    tool = GraphWriteTool(graph_writer=graph_writer, idempotency_store=idempotency_store)
    existing = find_matching_pattern(
        reader, person_id=correction.person_id, blocker_type=correction.corrected_blocker_type
    )
    detail = f"{correction.correction_note} (obligation {correction.obligation_id})"

    if existing is None:
        pattern_id = _write_new_pattern(
            tool,
            correction=correction,
            person_display_name=person_display_name,
            detail=detail,
        )
    else:
        pattern_id = _increment_pattern(
            tool,
            existing=existing,
            correction=correction,
            person_display_name=person_display_name,
            detail=detail,
        )

    _write_characterizes_edge(tool, pattern_id=pattern_id, correction=correction)
    return pattern_id


def _write_new_pattern(
    tool: GraphWriteTool, *, correction: DiagnosisCorrection, person_display_name: str, detail: str
) -> NodeId:
    pattern = Pattern(
        id=NodeId(f"pattern:{uuid.uuid4().hex}"),
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=_pattern_confidence(1),
            deriving_agent=_DERIVING_AGENT,
            created_at=correction.corrected_at,
        ),
        description=_pattern_description(
            blocker_type=correction.corrected_blocker_type,
            person_display_name=person_display_name,
            detail=detail,
        ),
        support_count=1,
        contributing_outcome_ids=(),
    )
    node_key = f"{correction.person_id}:write_friction_pattern:{correction.corrected_blocker_type.value}:1"
    result = tool.invoke_idempotent(node_key, operation="write_node", node=pattern)
    if not result.ok or result.value is None:
        raise ToolFailure(
            tool_name="graph_writer", reason=result.error or "friction pattern write failed", retryable=True
        )
    return NodeId(str(result.value))


def _increment_pattern(
    tool: GraphWriteTool,
    *,
    existing: Pattern,
    correction: DiagnosisCorrection,
    person_display_name: str,
    detail: str,
) -> NodeId:
    new_support_count = existing.support_count + 1
    new_pattern = Pattern(
        id=NodeId(f"pattern:{uuid.uuid4().hex}"),
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=_pattern_confidence(new_support_count),
            deriving_agent=_DERIVING_AGENT,
            created_at=correction.corrected_at,
        ),
        description=_pattern_description(
            blocker_type=correction.corrected_blocker_type,
            person_display_name=person_display_name,
            detail=detail,
        ),
        support_count=new_support_count,
        contributing_outcome_ids=existing.contributing_outcome_ids,
    )
    node_key = (
        f"{correction.person_id}:write_friction_pattern:"
        f"{correction.corrected_blocker_type.value}:{new_support_count}"
    )
    result = tool.invoke_idempotent(
        node_key, operation="supersede_node", old_node_id=str(existing.id), new_node=new_pattern
    )
    if not result.ok or result.value is None:
        raise ToolFailure(
            tool_name="graph_writer",
            reason=result.error or "friction pattern supersession failed",
            retryable=True,
        )
    new_id = NodeId(str(result.value))

    supersedes_edge = Edge(
        id=EdgeId(f"edge:{uuid.uuid4().hex}"),
        provenance=new_pattern.provenance,
        edge_type=EdgeType.SUPERSEDES,
        from_id=new_id,
        to_id=existing.id,
    )
    edge_key = f"{new_id}:write_supersedes_edge:{existing.id}"
    edge_result = tool.invoke_idempotent(edge_key, operation="write_edge", edge=supersedes_edge)
    if not edge_result.ok:
        raise ToolFailure(
            tool_name="graph_writer",
            reason=edge_result.error or "supersedes edge write failed",
            retryable=True,
        )
    return new_id


def _write_characterizes_edge(
    tool: GraphWriteTool, *, pattern_id: NodeId, correction: DiagnosisCorrection
) -> None:
    edge = Edge(
        id=EdgeId(f"edge:{uuid.uuid4().hex}"),
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=1.0,
            deriving_agent=_DERIVING_AGENT,
            created_at=correction.corrected_at,
        ),
        edge_type=EdgeType.CHARACTERIZES,
        from_id=pattern_id,
        to_id=correction.person_id,
    )
    edge_key = f"{pattern_id}:write_characterizes_edge:{correction.person_id}"
    result = tool.invoke_idempotent(edge_key, operation="write_edge", edge=edge)
    if not result.ok:
        raise ToolFailure(
            tool_name="graph_writer", reason=result.error or "characterizes edge write failed", retryable=True
        )


__all__ = [
    "apply_diagnosis_correction",
    "extract_blocker_type_from_pattern",
    "find_matching_pattern",
    "summarise_for_person",
]
