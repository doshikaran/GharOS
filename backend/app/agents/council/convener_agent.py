"""A41 — Council Convener (spec §12.3 Phase 0, §15.9, PHASES.md Phase 12,
ADR-019) — E2's `backend/app/agents/council/`.

*Responsibility:* dynamic composition. Given a trigger (a stated
intention, a Ledger/Simulator signal) and the household's real people,
decides which of the five specialists (A42-A46) and which member delegates
a *this* decision actually warrants — a car decision convenes
Finance+Logistics+Care+adult delegates+an elder delegate if materially
affected; a house decision additionally convenes Education+Legal (spec
§12.4/§12.5). Writes a real `Decision` node, `status=OPEN`, via
`GraphWriter.write_node` — the one real write this agent performs.

*Model tier:* Pro-tier (`model_router.PRO_TIER_ALLOWLIST`) — deciding
which specialists and delegates a genuinely novel household decision
warrants is judgment over real household composition, never a lookup.

*Forbidden:* **holding a position itself** — enforced structurally:
`types.CouncilComposition` has no stance/reasoning-about-the-decision
field, only participant selection (see that dataclass's own docstring).
This module's prompt asks the model only to select participants; nothing
in `CouncilComposition`'s shape could carry an opinion even if a model
tried to volunteer one in free text — the only string fields this
dataclass exposes at all are `question`/`trigger`, both echoing the
caller's own input back, never model-generated commentary.
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
from .json_utils import parse_json_response, require_list
from .types import ConvenerRequest, CouncilComposition, HouseholdMemberSummary

AGENT_ID = AgentId("A41")

_ALL_SPECIALIST_IDS = frozenset({"A42", "A43", "A44", "A45", "A46"})


def _members_block(members: tuple[HouseholdMemberSummary, ...]) -> str:
    if not members:
        return "(no household members were supplied)"
    lines = []
    for member in members:
        note = member.materially_affected_note or "no specific note supplied"
        lines.append(f"- [{member.person_id}] {member.display_name} (role={member.role}): {note}")
    return "\n".join(lines)


class CouncilConvenerAgent:
    """A41 Council Convener. Dependency-injected on a `GeminiClient` plus
    a `GraphWriter`/`IdempotencyStore` pair for the one real write this
    agent performs, wrapped immediately into a T3-only `ToolRegistry`
    (mirrors `app.agents.simulator.decision_framing_agent.
    DecisionFramingAgent`'s identical construction pattern one phase
    earlier)."""

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
        `DecisionFramingAgent.tool_registry` is — a test can assert this
        agent holds no tool above T3 without running it."""
        return self._tool_registry

    def convene(self, request: ConvenerRequest, *, cycle_id: str) -> CouncilComposition:
        """Selects this decision's real specialists and delegates, and
        writes the real `Decision` node they will report against.

        Args:
            request: the real question/trigger and the household's real,
                pre-resolved members.
            cycle_id: identifies this convening round for idempotency (a
                retry with the same `cycle_id` never double-writes the
                `Decision` node).

        Returns:
            A `CouncilComposition` whose `decision_id` is the real written
            node's id, `convened_specialist_ids` a real subset of
            `{"A42", ..., "A46"}`, and `convened_delegate_person_ids` a
            real subset of `request.household_members`' own ids.

        Raises:
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape, named a specialist id
                outside the real five, or named a delegate person id not
                present in `request.household_members`.
            contracts.errors.ToolFailure: the `Decision` node failed to
                write.
        """
        prompt = load_prompt("A41")
        rendered = prompt.text.format(
            question=request.question,
            trigger=request.trigger,
            members_block=_members_block(request.household_members),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        specialist_ids = self._validated_specialist_ids(parsed, raw_text=call_result.text)
        delegate_ids = self._validated_delegate_ids(
            parsed, household_members=request.household_members, raw_text=call_result.text
        )

        decision_id = self._write_decision(
            question=request.question, trigger=request.trigger, cycle_id=cycle_id
        )
        return CouncilComposition(
            decision_id=decision_id,
            question=request.question,
            trigger=request.trigger,
            convened_specialist_ids=specialist_ids,
            convened_delegate_person_ids=delegate_ids,
        )

    def _validated_specialist_ids(self, parsed: dict[str, object], *, raw_text: str) -> tuple[str, ...]:
        raw_ids = require_list(parsed, "convened_specialist_ids", agent_id=AGENT_ID)
        specialist_ids: list[str] = []
        for raw_id in raw_ids:
            if not isinstance(raw_id, str) or raw_id not in _ALL_SPECIALIST_IDS:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"convened_specialist_ids contains {raw_id!r}, not a real specialist id",
                    raw_text=raw_text,
                )
            if raw_id not in specialist_ids:
                specialist_ids.append(raw_id)
        if not specialist_ids:
            raise ModelResponseMalformed(
                agent_id=AGENT_ID, reason="convened_specialist_ids must not be empty", raw_text=raw_text
            )
        return tuple(specialist_ids)

    def _validated_delegate_ids(
        self,
        parsed: dict[str, object],
        *,
        household_members: tuple[HouseholdMemberSummary, ...],
        raw_text: str,
    ) -> tuple[NodeId, ...]:
        real_ids = {member.person_id for member in household_members}
        raw_ids = require_list(parsed, "convened_delegate_person_ids", agent_id=AGENT_ID)
        delegate_ids: list[NodeId] = []
        for raw_id in raw_ids:
            if not isinstance(raw_id, str) or NodeId(raw_id) not in real_ids:
                raise ModelResponseMalformed(
                    agent_id=AGENT_ID,
                    reason=f"convened_delegate_person_ids contains {raw_id!r}, not a real household member",
                    raw_text=raw_text,
                )
            candidate = NodeId(raw_id)
            if candidate not in delegate_ids:
                delegate_ids.append(candidate)
        return tuple(delegate_ids)

    def _write_decision(self, *, question: str, trigger: str, cycle_id: str) -> NodeId:
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

        key = IdempotencyKey(
            entity_id=cycle_id, action_type="write_council_decision", cycle=cycle_id
        ).as_str()
        result = tool.invoke_idempotent(key, operation="write_node", node=decision)
        if not result.ok or result.value is None:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=result.error or "council decision write failed",
                retryable=True,
            )
        return NodeId(str(result.value))


__all__ = ["AGENT_ID", "CouncilConvenerAgent"]
