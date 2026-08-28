"""A38 — Consistency Critic (spec §11.3, §15.8, PHASES.md Phase 11,
ADR-017) — E2's `backend/app/agents/simulator/`.

*Responsibility:* red-team exactly **one already-produced**
`types.BranchProjection` for wishful thinking, omitted second-order
effects, and optimism bias — spec §15.8 A38: "critiques *another* agent's
output," the pattern that works, never self-critique (this module never
imports or calls `path_simulator_agent`, and never re-runs the projection
itself). Appends the resulting critique text onto the real `Branch`
node's `critiques` tuple via `GraphWriter.supersede_node` — nodes are
immutable-versioned (PHASES.md §2.2), so "adding a critique" always means
reading the current version and writing a new one, never a mutation.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`), elevated
thinking (`_THINKING_BUDGET` — this agent's own justified constant, per
`GeminiClient.generate_structured`'s opt-in pattern, mirroring
`path_simulator_agent._THINKING_BUDGET`'s identical rationale one phase
earlier in the same pipeline stage: genuinely checking a branch's claims
against real graph data for wishful thinking is multi-step adversarial
reasoning, not a lookup).

*Forbidden:* self-critique (structurally impossible — this module's only
public method takes a `types.CritiqueRequest` carrying someone else's
already-produced `BranchProjection`, never re-derives one of its own).
Never silently accepts a clean projection without saying so —
`revised_confidence_note` is always populated, even when nothing
over-optimistic was found (see `types.BranchCritique`'s own docstring).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.actions import IdempotencyKey
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import AgentId, Branch, Derivation, NodeId, Provenance
from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from .errors import BranchNotFound, ModelResponseMalformed
from .json_utils import parse_json_response, require_str, require_str_tuple
from .types import BranchCritique, CritiqueRequest

AGENT_ID = AgentId("A38")

_THINKING_BUDGET = 12000
"""This agent's own justified elevated-thinking budget (never inherited
from another agent's constant, per `GeminiClient.generate_structured`'s
own docstring) — genuinely checking a branch's claims against real graph
data for optimism bias and second-order effects is multi-step adversarial
reasoning over several independent real entities, not a single lookup."""


def _impacts_block(projected_impacts: dict[str, str]) -> str:
    if not projected_impacts:
        return "(no projected impacts were given)"  # pragma: no cover — A37 always populates one
    return "\n".join(f"- {category}: {claim}" for category, claim in projected_impacts.items())


def _refs_block(refs: tuple[str, ...]) -> str:
    if not refs:
        return "(no external grounding was cited for this branch)"
    return "\n".join(f"- {ref}" for ref in refs)


def _context_block(context: tuple[str, ...]) -> str:
    if not context:
        return "(no real household entities were found within this branch's blast radius)"
    return "\n".join(f"- {fact}" for fact in context)


def _format_critique_text(critique: BranchCritique) -> str:
    """The one string appended to the real `Branch.critiques` tuple for
    this critique pass — a plain, human-readable record of everything
    this method found, never split across several tuple entries (mirrors
    `types.BranchCritique`'s own "entire output... as one critique" shape)."""
    parts = [f"[A38] {critique.revised_confidence_note}"]
    if critique.over_optimistic_claims:
        parts.append("Over-optimistic claims: " + "; ".join(critique.over_optimistic_claims))
    if critique.omitted_second_order_effects:
        parts.append("Omitted second-order effects: " + "; ".join(critique.omitted_second_order_effects))
    return " ".join(parts)


class ConsistencyCriticAgent:
    """A38 Consistency Critic. Dependency-injected on a `GeminiClient`, a
    bare `GraphReader` (T0-equivalent — mirrors `PathSimulatorAgent`'s own
    precedent for a real read this phase's `GraphReadTool` dispatch table
    does not cover: here, re-reading the current `Branch` version this
    critique must append onto), plus a `GraphWriter`/`IdempotencyStore`
    pair wrapped into a T3-only `ToolRegistry` for the one real write this
    agent performs."""

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
        `PathSimulatorAgent.tool_registry` is — a test can assert this
        agent holds no tool above T3 without running it."""
        return self._tool_registry

    def critique(self, request: CritiqueRequest, *, cycle_id: str) -> BranchCritique:
        """Red-teams `request.branch_projection` and appends the result
        onto the real `Branch` node's `critiques` tuple.

        Args:
            request: exactly one already-produced `BranchProjection`, its
                branch's real topic, and the real blast-radius summaries
                A37 saw for it — never another branch's data.
            cycle_id: identifies this critique round for idempotency (a
                retry with the same `cycle_id` never appends the same
                critique twice).

        Returns:
            A `BranchCritique` for `request.branch_projection.branch_id`.
            `revised_confidence_note` is always populated.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or
                `revised_confidence_note` was blank.
            errors.BranchNotFound: `request.branch_projection.branch_id`
                does not currently resolve to a real `Branch` node.
            contracts.errors.ToolFailure: the updated `Branch` node failed
                to write.
        """
        projection = request.branch_projection
        prompt = load_prompt("A38")
        rendered = prompt.text.format(
            branch_label=projection.label,
            branch_topic=request.branch_topic,
            projected_impacts_block=_impacts_block(projection.projected_impacts),
            grounding_refs_block=_refs_block(projection.grounding_refs),
            blast_radius_context_block=_context_block(request.blast_radius_context),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered, thinking_budget=_THINKING_BUDGET
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        over_optimistic_claims = require_str_tuple(parsed, "over_optimistic_claims", agent_id=AGENT_ID)
        omitted_second_order_effects = require_str_tuple(
            parsed, "omitted_second_order_effects", agent_id=AGENT_ID
        )
        revised_confidence_note = require_str(parsed, "revised_confidence_note", agent_id=AGENT_ID)
        if not revised_confidence_note.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID,
                reason="revised_confidence_note must not be blank",
                raw_text=call_result.text,
            )

        critique = BranchCritique(
            branch_id=projection.branch_id,
            over_optimistic_claims=over_optimistic_claims,
            omitted_second_order_effects=omitted_second_order_effects,
            revised_confidence_note=revised_confidence_note,
        )
        self._append_critique(
            branch_id=projection.branch_id,
            critique_text=_format_critique_text(critique),
            cycle_id=cycle_id,
        )
        return critique

    def _append_critique(self, *, branch_id: NodeId, critique_text: str, cycle_id: str) -> None:
        current = self._graph_reader.get_node(branch_id)
        if not isinstance(current, Branch):
            raise BranchNotFound(agent_id=AGENT_ID, branch_id=branch_id)

        updated = Branch(
            id=NodeId(f"branch:{uuid.uuid4().hex}"),
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=1.0,
                deriving_agent=AGENT_ID,
                created_at=datetime.now(UTC),
            ),
            decision_id=current.decision_id,
            label=current.label,
            projected_impacts=current.projected_impacts,
            grounding_refs=current.grounding_refs,
            critiques=current.critiques + (critique_text,),
        )
        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present

        key = IdempotencyKey(
            entity_id=str(branch_id), action_type="write_branch_critique", cycle=cycle_id
        ).as_str()
        result = tool.invoke_idempotent(
            key, operation="supersede_node", old_node_id=str(branch_id), new_node=updated
        )
        if not result.ok or result.value is None:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=result.error or "branch critique supersede failed",
                retryable=True,
            )


__all__ = ["AGENT_ID", "ConsistencyCriticAgent"]
