"""A37 — Path Simulator (spec §11.3, §15.8, PHASES.md Phase 11, ADR-017)
— E2's `backend/app/agents/simulator/`.

*Responsibility:* project **exactly one branch** across the entire graph
— per spec §15.8: "instantiated per branch, parallel" — genuinely
independent, parallel exploration of one option, never several agents
arguing toward a shared answer. This module's `simulate()` method signature
is the structural guarantee: it takes exactly one `types.
PathSimulationRequest` (one branch's own topic, candidate anchors, and
grounding) and returns exactly one `types.BranchProjection` — there is no
parameter through which it could see or be influenced by another branch's
data or output, and no instance state is mutated across calls (see
`TestGenuineIndependence` in `backend/tests/test_path_simulator_agent.py`
for the direct proof: two calls with swapped/different fixture data on
the *same* agent instance produce fully independent results).

Derives real anchor `NodeId`s from the graph (people/obligations/
constraints touching the decision's actual topic — PHASES.md Phase 11
work item) via `context.resolve_real_anchor_ids`, then calls
`GraphReader.blast_radius_multi` on them (ADR-017) — one real traversal
over several real anchors, "blast radius at decision scale." `graph_reader`
is held directly (not wrapped in `app.tools.graph_read_tool.GraphReadTool`
— that T0 tool's dispatch table predates Phase 11 and does not yet cover
`blast_radius_multi`; see this package's own report for the flagged gap).
This is read-only access (T0-equivalent; mirrors
`app.agents.concierge.context`'s established "bare `GraphReader` function
parameter, no wrapper" precedent for pure reads) — the *write* half
(the `Branch` node itself) goes through the real T3 `GraphWriteTool` via
`ToolRegistry`, exactly like every other writer agent in this codebase.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`), elevated
thinking (`_THINKING_BUDGET` — this agent's own justified constant, per
`GeminiClient.generate_structured`'s opt-in pattern: projecting a branch
across an entire household's obligations, constraints, and people is
exactly the kind of multi-step reasoning elevated thinking budgets exist
for, spec §21.1 "branch simulation & critique").

*Forbidden:* **comparing branches** — structurally impossible, since no
sibling-branch data ever reaches this method. **Self-assessing its own
quality** — the prompt explicitly forbids it, and this module never
parses or surfaces a model self-rating beyond the plain numeric
`confidence` field (which this module does not even propagate onto
`BranchProjection` — that dataclass has no confidence field to smuggle
one into).

**Structural traceability (Gate 11: "every branch claim traceable to
graph data or a cited source"):** `projected_impacts` always contains a
`"graph_blast_radius"` entry computed by this module's own code, never by
the model — a real, deterministic summary of the real blast-radius nodes
found, so at least one entry is graph data by construction regardless of
what the model's own projections say.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.actions import IdempotencyKey
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Branch,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
)
from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient, GroundedCitation
from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from . import context
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_dict
from .types import BranchProjection, GroundingResult, PathSimulationRequest

AGENT_ID = AgentId("A37")

_THINKING_BUDGET = 12000
"""This agent's own justified elevated-thinking budget (never inherited
from another agent's constant, per `GeminiClient.generate_structured`'s
own docstring) — projecting one branch's impact across an entire
household's real obligations, constraints, and people is genuinely
multi-step reasoning: it must weigh several independent real entities
(a board-exam year, a dialysis schedule, a staff member's tenure) against
one topic simultaneously, not answer a single lookup."""


def format_grounding_ref(citation: GroundedCitation) -> str:
    """The formal `grounding_refs` string convention this phase
    establishes (ADR-017/this phase's brief): `"<title> (<uri>) —
    retrieved <ISO8601>"`. A module-level function (not private) — A38's
    critique fixtures and package-level integration tests build the same
    string shape to assert against, so it is shared rather than
    duplicated."""
    return f"{citation.title} ({citation.uri}) — retrieved {citation.retrieved_at.isoformat()}"


def _grounding_block(grounding: GroundingResult | None) -> str:
    if grounding is None or (not grounding.citations and not grounding.summary):
        return "(no external research was provided for this branch)"
    lines = [f"Summary: {grounding.summary}", f"Freshness: {grounding.freshness_note}"]
    for citation in grounding.citations:
        lines.append(f"- {format_grounding_ref(citation)}")
    return "\n".join(lines)


def _validate_str_dict(value: dict[str, object], *, raw_text: str) -> dict[str, str]:
    validated: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(item, str):
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason=f"projected_impacts[{key!r}] must be a string, got {type(item).__name__}",
                raw_text=raw_text,
            )
        validated[key] = item
    return validated


class PathSimulatorAgent:
    """A37 Path Simulator. One instance may safely be reused across many
    branches (that is the whole point of "instantiated per branch,
    parallel") because it holds no per-call mutable state — every fact a
    given `simulate()` call reasons over comes from that call's own
    `PathSimulationRequest` and a fresh graph read, never from a prior
    call's leftovers.
    """

    def __init__(
        self,
        *,
        gemini_client: GeminiClient,
        graph_reader: GraphReader,
        graph_writer: GraphWriter,
        idempotency_store: IdempotencyStore,
    ) -> None:
        self._gemini_client = gemini_client
        self._graph_reader = graph_reader
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T3_INTERNAL_WRITE})
        )
        self._tool_registry.register(
            GraphWriteTool(graph_writer=graph_writer, idempotency_store=idempotency_store)
        )

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed for the same adversarial-proof reason
        `RenegotiationTriggerAgent.tool_registry` is."""
        return self._tool_registry

    def simulate(self, request: PathSimulationRequest, *, cycle_id: str) -> BranchProjection:
        """Projects exactly `request`'s one branch across the graph.

        Args:
            request: this one branch's own topic, candidate anchor ids,
                and (optional) external grounding — never another
                branch's data.
            cycle_id: identifies this simulation round for idempotency
                (combined with `request.branch_label` so two different
                branches in the same round never collide on one key).

        Returns:
            A `BranchProjection` whose `branch_id` is the real written
            `Branch` node's id, whose `blast_radius_node_ids` is the real
            id set `GraphReader.blast_radius_multi` returned, and whose
            `projected_impacts` always includes a code-computed
            `"graph_blast_radius"` entry.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or a projected
                impact value was not a string.
            contracts.errors.ToolFailure: the `Branch` node failed to
                write.
        """
        real_anchor_ids = context.resolve_real_anchor_ids(
            self._graph_reader, candidate_ids=request.candidate_anchor_ids
        )
        blast_nodes = self._graph_reader.blast_radius_multi(real_anchor_ids, request.blast_radius_depth)
        blast_node_ids = tuple(
            NodeId(str(node.id)) for node in blast_nodes if hasattr(node, "id")
        )
        graph_summaries = context.summarize_anchor_nodes(blast_nodes)
        graph_context_block = (
            "\n".join(f"- {summary}" for summary in graph_summaries)
            if graph_summaries
            else "(no real household entities found within blast radius for this branch's anchors)"
        )

        prompt = load_prompt("A37")
        rendered = prompt.text.format(
            branch_label=request.branch_label,
            branch_topic=request.branch_topic,
            graph_context_block=graph_context_block,
            grounding_block=_grounding_block(request.grounding),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered, thinking_budget=_THINKING_BUDGET
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        model_impacts = _validate_str_dict(
            require_dict(parsed, "projected_impacts", agent_id=AGENT_ID), raw_text=call_result.text
        )

        graph_derived_summary = (
            f"{len(blast_node_ids)} real household entities within {request.blast_radius_depth} hop(s) "
            f"of {len(real_anchor_ids)} anchor(s): "
            + ("; ".join(graph_summaries) if graph_summaries else "none found")
        )
        # This entry is always code-computed, never model prose — Gate 11's
        # "every branch claim traceable to graph data" guarantee for at
        # least this one entry, regardless of the model's own output.
        projected_impacts = {**model_impacts, "graph_blast_radius": graph_derived_summary}

        grounding_refs = (
            tuple(format_grounding_ref(c) for c in request.grounding.citations)
            if request.grounding is not None
            else ()
        )

        branch_id = self._write_branch(
            decision_id=request.decision_id,
            label=request.branch_label,
            projected_impacts=projected_impacts,
            grounding_refs=grounding_refs,
            cycle_id=cycle_id,
        )
        return BranchProjection(
            branch_id=branch_id,
            label=request.branch_label,
            projected_impacts=projected_impacts,
            grounding_refs=grounding_refs,
            blast_radius_node_ids=blast_node_ids,
        )

    def _write_branch(
        self,
        *,
        decision_id: NodeId,
        label: str,
        projected_impacts: dict[str, str],
        grounding_refs: tuple[str, ...],
        cycle_id: str,
    ) -> NodeId:
        branch_id = NodeId(f"branch:{uuid.uuid4().hex}")
        # A branch projection synthesizes real graph traversal plus
        # (optionally) real external grounding rather than one single
        # source document — `Provenance`'s own documented
        # AMBIGUOUS-with-no-single-source carve-out (same precedent
        # `decision_framing_agent._write_decision` uses) is the honest
        # choice here.
        provenance = Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=1.0,
            deriving_agent=AGENT_ID,
            created_at=datetime.now(UTC),
        )
        branch = Branch(
            id=branch_id,
            provenance=provenance,
            decision_id=decision_id,
            label=label,
            projected_impacts=projected_impacts,
            grounding_refs=grounding_refs,
            critiques=(),
        )
        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present

        node_key = IdempotencyKey(
            entity_id=f"{decision_id}:{label}", action_type="write_branch_projection", cycle=cycle_id
        ).as_str()
        node_result = tool.invoke_idempotent(node_key, operation="write_node", node=branch)
        if not node_result.ok or node_result.value is None:
            raise ToolFailure(
                tool_name="graph_writer", reason=node_result.error or "branch projection write failed",
                retryable=True,
            )
        written_id = NodeId(str(node_result.value))

        edge_key = IdempotencyKey(
            entity_id=f"{decision_id}:{label}", action_type="write_branch_contains_edge", cycle=cycle_id
        ).as_str()
        edge = Edge(
            id=EdgeId(f"edge:{uuid.uuid4().hex}"),
            provenance=provenance,
            edge_type=EdgeType.CONTAINS,
            from_id=decision_id,
            to_id=written_id,
        )
        edge_result = tool.invoke_idempotent(edge_key, operation="write_edge", edge=edge)
        if not edge_result.ok:
            raise ToolFailure(
                tool_name="graph_writer", reason=edge_result.error or "contains edge write failed",
                retryable=True,
            )
        return written_id


__all__ = ["AGENT_ID", "PathSimulatorAgent", "format_grounding_ref"]
