"""A20 — Renegotiation Trigger (spec §8.3 Stage 5, §15.8).

*Responsibility:* monitor for real life events warranting re-allocation —
a new or changed hard `SCHEDULE`-kind `Constraint` (e.g. "started night
shifts"), or a `Person` capability flag change. Produces a real, typed
`types.RenegotiationTrigger` — it never re-solves itself; it signals that
a new A17-A21 cycle should run.

*Model tier:* Flash. A capability flag flip is unambiguous and needs no
model judgment at all (`evaluate_capability_change` is pure deterministic
code, no Gemini call, always renegotiation-worthy by construction). A
schedule-constraint change needs a real, if lightweight, judgment call on
*significance* — "started night shifts" versus a ten-minute timing tweak
— which is exactly Flash-tier classification work
(`evaluate_schedule_change`).

## The `CONCEDED_BY` half — E1's Phase 8 finding, answered for real

E1's own Phase 8 final report noted, honestly, that nothing yet writes a
`CONCEDED_BY` edge from an actual renegotiation. This module is that real
answer: `detect_concession` deterministically compares a person's prior
and new bundle costs *under their own current valuation* (never mixing
valuations across cycles), and `record_concession` writes a real
`Decision` node plus a `CONCEDED_BY` edge to the conceding person via a
T3 write tool, exactly when `detect_concession` finds real evidence a
concession happened — never speculatively, never for every renegotiation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.actions import IdempotencyKey
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Constraint,
    Decision,
    DecisionStatus,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
)
from contracts.repositories import GraphWriter, IdempotencyStore
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from .errors import ConcessionCostDataMissing
from .json_utils import parse_json_response, require_bool, require_float, require_str
from .types import (
    CapabilityChangeSignal,
    ConcessionCheckRequest,
    ConcessionEvidence,
    RenegotiationTrigger,
    ScheduleConstraintChangeSignal,
)

AGENT_ID = AgentId("A20")


def _constraint_block(constraint: Constraint | None) -> str:
    if constraint is None:
        return "(none — this is a brand-new constraint)"
    return (
        f"kind={constraint.kind.value} severity={constraint.severity.value} "
        f'structured={constraint.structured} original_text="{constraint.original_text}"'
    )


class RenegotiationTriggerAgent:
    """A20 Renegotiation Trigger. Dependency-injected on a `GeminiClient`
    plus a `GraphWriter`/`IdempotencyStore` pair for the `record_concession`
    path only, wrapped immediately into a T3-only `ToolRegistry`."""

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
        `StaffPayrollAgent.tool_registry` is."""
        return self._tool_registry

    def evaluate_capability_change(self, signal: CapabilityChangeSignal) -> RenegotiationTrigger:
        """Deterministic — no model call. A capability flag flip is
        always renegotiation-worthy (unlike a schedule constraint's
        free-text severity, a boolean flip has no ambiguity to judge)."""
        return RenegotiationTrigger(
            trigger_id=uuid.uuid4().hex,
            person_id=signal.person_id,
            reason_kind="capability_change",
            detail=f"{signal.capability_name} changed from {signal.old_value} to {signal.new_value}",
            detected_at=datetime.now(UTC),
            confidence=1.0,
        )

    def evaluate_schedule_change(self, signal: ScheduleConstraintChangeSignal) -> RenegotiationTrigger | None:
        """Flash: judges whether a real schedule-constraint change is
        significant enough to warrant re-allocation.

        Args:
            signal: the real new (and, if applicable, previous)
                `SCHEDULE`-kind hard `Constraint`.

        Returns:
            A `RenegotiationTrigger` when the model judges this
            significant, else `None`.

        Raises:
            errors.ModelResponseMalformed: the model's response could not
                be parsed as the expected JSON shape.
        """
        prompt = load_prompt("A20")
        rendered = prompt.text.format(
            person_id=signal.person_id,
            new_constraint_block=_constraint_block(signal.new_constraint),
            previous_constraint_block=_constraint_block(signal.previous_constraint),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        significant = require_bool(parsed, "significant", agent_id=AGENT_ID, default=False)
        if not significant:
            return None
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.0)
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)

        return RenegotiationTrigger(
            trigger_id=uuid.uuid4().hex,
            person_id=signal.person_id,
            reason_kind="schedule_constraint_change",
            detail=reasoning,
            detected_at=datetime.now(UTC),
            confidence=confidence,
        )

    def detect_concession(self, request: ConcessionCheckRequest) -> ConcessionEvidence | None:
        """Deterministic — no model call. Prices both the prior and new
        bundle under `request.current_costs_for_person` (one consistent
        valuation) and returns real evidence only when the new bundle
        genuinely costs this person more.

        Returns:
            `ConcessionEvidence` when `new_bundle_cost > prior_bundle_cost`
            strictly, else `None` (no concession — their new share is not
            worse, under their own current valuation).

        Raises:
            errors.ConcessionCostDataMissing: a task in either bundle has
                no priced entry in `request.current_costs_for_person` —
                never silently treated as costing nothing.
        """
        costs = request.current_costs_for_person
        for task_id in (*request.prior_bundle_task_ids, *request.new_bundle_task_ids):
            if str(task_id) not in costs:
                raise ConcessionCostDataMissing(person_id=request.person_id, missing_task_id=task_id)

        prior_cost = sum(costs[str(t)] for t in request.prior_bundle_task_ids)
        new_cost = sum(costs[str(t)] for t in request.new_bundle_task_ids)
        if new_cost <= prior_cost:
            return None

        return ConcessionEvidence(
            person_id=request.person_id,
            prior_bundle_cost=prior_cost,
            new_bundle_cost=new_cost,
            reasoning=(
                f"after '{request.renegotiation_reason}', {request.person_id}'s new bundle costs "
                f"{new_cost:.2f} under their own current valuation, versus {prior_cost:.2f} for their "
                "prior bundle — a real, computed concession, not a guess."
            ),
        )

    def record_concession(self, evidence: ConcessionEvidence, *, allocation_cycle_id: str) -> NodeId:
        """Writes a real `Decision` node plus a `CONCEDED_BY` edge to the
        conceding person, via the T3 write tool.

        Args:
            evidence: the real, computed concession evidence.
            allocation_cycle_id: identifies this renegotiation round for
                idempotency.

        Returns:
            The written `Decision` node's id.

        Raises:
            contracts.errors.ToolFailure: the `Decision` node or its
                `CONCEDED_BY` edge failed to write.
        """
        decision_id = NodeId(f"decision:{uuid.uuid4().hex}")
        # A concession is a computed comparison across two allocation
        # cycles' bundle costs — there is no single SOURCE_DOCUMENT this
        # Decision can honestly point at. `contracts.graph_types.
        # Provenance`'s own docstring names exactly this "no single
        # source" shape as the intended use of `Derivation.AMBIGUOUS` with
        # `source_ref=None` (same precedent `valuation_extraction_agent.py`
        # follows for `ValuationProfile`).
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
            question=f"Renegotiation: {evidence.person_id}'s share after a detected life event",
            trigger=evidence.reasoning,
            status=DecisionStatus.RESOLVED,
            resolution_summary=(
                f"{evidence.person_id} accepted a costlier share "
                f"({evidence.new_bundle_cost:.2f} vs {evidence.prior_bundle_cost:.2f})"
            ),
            rationale=evidence.reasoning,
        )

        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present

        node_key = IdempotencyKey(
            entity_id=str(evidence.person_id),
            action_type="record_concession_decision",
            cycle=allocation_cycle_id,
        ).as_str()
        node_result = tool.invoke_idempotent(node_key, operation="write_node", node=decision)
        if not node_result.ok or node_result.value is None:
            raise ToolFailure(
                tool_name="graph_writer", reason=node_result.error or "concession decision write failed",
                retryable=True,
            )
        written_id = NodeId(str(node_result.value))

        edge_key = IdempotencyKey(
            entity_id=str(written_id), action_type="record_concession_edge", cycle=allocation_cycle_id
        ).as_str()
        edge = Edge(
            id=EdgeId(f"edge:{uuid.uuid4().hex}"),
            provenance=provenance,
            edge_type=EdgeType.CONCEDED_BY,
            from_id=written_id,
            to_id=evidence.person_id,
        )
        edge_result = tool.invoke_idempotent(edge_key, operation="write_edge", edge=edge)
        if not edge_result.ok:
            raise ToolFailure(
                tool_name="graph_writer", reason=edge_result.error or "conceded_by edge write failed",
                retryable=True,
            )
        return written_id


__all__ = ["AGENT_ID", "RenegotiationTriggerAgent"]
