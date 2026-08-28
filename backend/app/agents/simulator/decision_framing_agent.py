"""A35 — Decision Framing (spec §11.3, §15.8, PHASES.md Phase 11, ADR-017)
— E2's `backend/app/agents/simulator/`.

*Responsibility:* clarify the real household decision; detect false
binaries ("move or stay" often hides a real third option — e.g. a hybrid
arrangement, a delayed timeline, remote work); surface unconsidered
options a household under stress rarely sees on its own. Writes/updates a
real `Decision` node (`status=OPEN`) via `GraphWriter.write_node` — this
is the one real write this agent performs; everything else is judgment.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) for the
forward-mode `frame()` path — spec §15.8 A35: detecting a false binary and
surfacing a genuinely unconsidered option in a real household decision is
judgment, never a lookup.

`frame_backward()` (ADR-017 decision 3 — backward mode's second entry
point, not a seventh agent) is deliberately **deterministic, no model
call at all**: "assume this plan failed — why?" is a fixed restatement of
the plan description, not a judgment call; there is no false binary to
detect and no branches to propose for a single evidence-linked backward
question (`DecisionFrame.is_false_binary=False`,
`unconsidered_options=()`, `proposed_branch_labels=()` structurally, on
every backward-mode frame).

*Forbidden:* nothing beyond what §15.8 names for A35 explicitly (no
forbidden list given), but this module also never projects consequences
or compares branches — that is A36/A37/A38's job.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.actions import IdempotencyKey
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Decision,
    DecisionStatus,
    Derivation,
    NodeId,
    Provenance,
)
from contracts.repositories import GraphWriter, IdempotencyStore
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from .errors import ModelResponseMalformed
from .json_utils import parse_json_response, require_bool, require_str, require_str_tuple
from .types import BackwardFramingRequest, DecisionFrame, DecisionFramingRequest

AGENT_ID = AgentId("A35")


def _labels_block(labels: tuple[str, ...]) -> str:
    if not labels:
        return "(the household proposed no concrete branch labels yet)"
    return "\n".join(f"- {label}" for label in labels)


def _context_block(context: tuple[str, ...]) -> str:
    if not context:
        return "(no additional known household context)"
    return "\n".join(f"- {fact}" for fact in context)


class DecisionFramingAgent:
    """A35 Decision Framing. Dependency-injected on a `GeminiClient` plus
    a `GraphWriter`/`IdempotencyStore` pair for the one real write this
    agent performs, wrapped immediately into a T3-only `ToolRegistry`
    (mirrors `app.agents.fair_allocator.renegotiation_trigger_agent.
    RenegotiationTriggerAgent`'s identical construction pattern)."""

    def __init__(
        self, *, gemini_client: GeminiClient, graph_writer: GraphWriter, idempotency_store: IdempotencyStore
    ) -> None:
        self._gemini_client = gemini_client
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T3_INTERNAL_WRITE})
        )
        self._tool_registry.register(
            GraphWriteTool(graph_writer=graph_writer, idempotency_store=idempotency_store)
        )

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed for the same adversarial-proof reason
        `RenegotiationTriggerAgent.tool_registry` is — a test can assert
        this agent holds no tool above T3 without running it."""
        return self._tool_registry

    def frame(self, request: DecisionFramingRequest, *, cycle_id: str) -> DecisionFrame:
        """Forward-mode framing: real judgment on false-binary detection
        and unconsidered options, then writes the real `Decision` node.

        Args:
            request: the household's real request text, the triggering
                event, any branch labels the household already proposed,
                and pre-resolved real household context.
            cycle_id: identifies this framing round for idempotency (a
                retry with the same `cycle_id` never double-writes the
                `Decision` node).

        Returns:
            A `DecisionFrame` whose `decision_id` is the real written
            node's id.

        Raises:
            errors.ModelResponseMalformed: the model response could not
                be parsed as the expected JSON shape, or proposed an
                "unconsidered option" that merely restates an
                already-proposed branch label.
            contracts.errors.ToolFailure: the `Decision` node failed to
                write.
        """
        prompt = load_prompt("A35")
        rendered = prompt.text.format(
            household_request_text=request.household_request_text,
            trigger=request.trigger,
            proposed_branch_labels_block=_labels_block(request.proposed_branch_labels),
            known_context_block=_context_block(request.known_household_context),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        question = require_str(parsed, "question", agent_id=AGENT_ID)
        if not question.strip():
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="question must not be blank", raw_text=call_result.text
            )
        is_false_binary = require_bool(parsed, "is_false_binary", agent_id=AGENT_ID, default=False)
        unconsidered_options = require_str_tuple(parsed, "unconsidered_options", agent_id=AGENT_ID)

        proposed_lower = {label.strip().lower() for label in request.proposed_branch_labels}
        for option in unconsidered_options:
            if option.strip().lower() in proposed_lower:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=(
                        f"'unconsidered option' {option!r} merely restates an already-proposed "
                        "branch label — not a genuinely unconsidered option"
                    ),
                    raw_text=call_result.text,
                )

        decision_id = self._write_decision(question=question, trigger=request.trigger, cycle_id=cycle_id)
        return DecisionFrame(
            decision_id=decision_id,
            question=question,
            trigger=request.trigger,
            is_false_binary=is_false_binary,
            unconsidered_options=unconsidered_options,
            proposed_branch_labels=request.proposed_branch_labels,
        )

    def frame_backward(self, request: BackwardFramingRequest, *, cycle_id: str) -> DecisionFrame:
        """Backward-mode framing (ADR-017 decision 3): "take a committed
        plan, assume it failed" — a fixed restatement, deliberately
        deterministic (no model call; see module docstring).

        Args:
            request: the plan description and its real
                `Outcome.attribution_tags` category tag.
            cycle_id: identifies this framing round for idempotency.

        Returns:
            A `DecisionFrame` with `is_false_binary=False` and
            `unconsidered_options=proposed_branch_labels=()`, structurally
            — a backward-mode question is not a fork.
        """
        question = f"Assume this plan failed — why? Plan: {request.plan_description}"
        trigger = f"backward-mode analysis requested for category '{request.category_tag}'"
        decision_id = self._write_decision(question=question, trigger=trigger, cycle_id=cycle_id)
        return DecisionFrame(
            decision_id=decision_id,
            question=question,
            trigger=trigger,
            is_false_binary=False,
            unconsidered_options=(),
            proposed_branch_labels=(),
        )

    def _write_decision(self, *, question: str, trigger: str, cycle_id: str) -> NodeId:
        """Writes a real, `status=OPEN` `Decision` node via the T3 write
        tool. A decision frame is a synthesis of a real household request
        (or backward-mode plan description) plus this agent's own
        judgment — there is no single `SOURCE_DOCUMENT` it can honestly
        point at, so `Derivation.AMBIGUOUS` with `source_ref=None` is used
        (the same precedent `app.agents.fair_allocator.
        renegotiation_trigger_agent.RenegotiationTriggerAgent.
        record_concession` establishes for an identically-shaped case)."""
        decision_id = NodeId(f"decision:{uuid.uuid4().hex}")
        provenance = Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=1.0,
            deriving_agent=AGENT_ID,
            created_at=datetime.now(UTC),
        )
        decision = Decision(
            id=decision_id,
            provenance=provenance,
            question=question,
            trigger=trigger,
            status=DecisionStatus.OPEN,
            resolution_summary=None,
            rationale=None,
        )
        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present

        key = IdempotencyKey(entity_id=cycle_id, action_type="write_decision_frame", cycle=cycle_id).as_str()
        result = tool.invoke_idempotent(key, operation="write_node", node=decision)
        if not result.ok or result.value is None:
            raise ToolFailure(
                tool_name="graph_writer", reason=result.error or "decision frame write failed", retryable=True
            )
        return NodeId(str(result.value))


__all__ = ["AGENT_ID", "DecisionFramingAgent"]
