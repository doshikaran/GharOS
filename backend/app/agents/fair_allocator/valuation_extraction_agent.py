"""A18 — Valuation Extraction Agent (spec §8.3 Stage 2, §15.8).

*Responsibility:* mutate complaint streams, interview answers (A17's real
`ComparativePreference` output), voice notes, and observed completion
history into one person's real cardinal cost matrix, written as a
`contracts.graph_types.ValuationProfile` with a `VALUATION_OF` edge.

*Model tier:* Pro-tier (already on `model_router.PRO_TIER_ALLOWLIST` since
Phase 2's mechanism proof — spec §21.1 "valuation extraction").

*Forbidden:* **solving.** This module has no import of
`app.solvers.fair_allocation` anywhere — it produces a `ValuationProfile`,
never an allocation.

*Failure mode (spec §15.8, named explicitly):* "sparse matrix -> request
coverage, never fabricate values." Enforced twice over: the prompt itself
instructs the model to omit any task it lacks real evidence for, and this
module additionally drops any returned task cost below
`_COST_CONFIDENCE_FLOOR` (or non-finite/negative) before it ever reaches
the written `ValuationProfile.costs` — a model that ignores the prompt's
own instruction and returns a low-confidence guess anyway still cannot
make it into the graph. `ValuationExtractionResult.omitted_task_ids` is
the positive, explicit record of every candidate task that did not make
it in, for a caller to "request coverage" against.

## Provenance — a genuinely multi-source node (no single anchor document)

A `ValuationProfile` aggregates complaint text, interview answers, voice
notes, and observed history — there is no single `SOURCE_DOCUMENT` this
node can honestly point at as *the* source. `contracts.graph_types.
Provenance`'s own docstring names exactly this situation as the intended
use of `Derivation.AMBIGUOUS` with `source_ref=None`: "None only for
AMBIGUOUS-with-no-single-source cases (e.g. a mined PATTERN with multiple
contributing OUTCOMEs)" — a `ValuationProfile` built from several
contributing evidence sources is structurally the same shape of fact as
that named example, so this module tags every `ValuationProfile` it
writes `Derivation.AMBIGUOUS`, `source_ref=None`, following that
documented precedent rather than picking one contributing source
arbitrarily and calling it "the" source.
"""

from __future__ import annotations

import math
import uuid
from datetime import UTC, datetime
from typing import Literal

from contracts.actions import IdempotencyKey
from contracts.agents import ModelTier
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
    ValuationProfile,
)
from contracts.repositories import GraphWriter, IdempotencyStore
from contracts.tools import PermissionTier

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from .json_utils import parse_json_response, require_float, require_list, require_str
from .types import ValuationExtractionRequest, ValuationExtractionResult

AGENT_ID = AgentId("A18")

_COST_CONFIDENCE_FLOOR = 0.5
"""Below this, an individual task's model-proposed cost is not trusted
enough to write — dropped from `costs` (sparse by omission) rather than
included at low confidence. Mirrors
`app.agents.ledger.staff_payroll_agent._MARK_RESOLUTION_CONFIDENCE_FLOOR`'s
same role: a floor below which this module refuses to act on the model's
output at all, never a value it silently lowers its standards to accept."""


def _candidate_tasks_block(request: ValuationExtractionRequest) -> str:
    lines = [
        f'- id="{task_id}" description="{request.task_descriptions[str(task_id)]}"'
        for task_id in request.candidate_task_ids
    ]
    return "\n".join(lines) if lines else "(no candidate tasks)"


def _complaint_texts_block(request: ValuationExtractionRequest) -> str:
    if not request.complaint_texts:
        return "(no complaint-stream text)"
    return "\n".join(f"- {text}" for text in request.complaint_texts)


def _comparative_preferences_block(request: ValuationExtractionRequest) -> str:
    if not request.comparative_preferences:
        return "(no interview answers yet)"
    lines = []
    for pref in request.comparative_preferences:
        if pref.preferred == "tie":
            lines.append(f"- {pref.task_a_id} and {pref.task_b_id} felt about the same")
        elif pref.preferred == "task_a":
            lines.append(f"- prefers {pref.task_a_id} over {pref.task_b_id}")
        else:
            lines.append(f"- prefers {pref.task_b_id} over {pref.task_a_id}")
    return "\n".join(lines)


def _voice_note_texts_block(request: ValuationExtractionRequest) -> str:
    if not request.voice_note_texts:
        return "(no voice notes)"
    return "\n".join(f"- {text}" for text in request.voice_note_texts)


def _observed_effort_block(request: ValuationExtractionRequest) -> str:
    if not request.observed_effort:
        return "(no observed completion history)"
    return "\n".join(f"- task {signal.task_id}: {signal.description}" for signal in request.observed_effort)


_ElicitationMethod = Literal["interview", "complaint_inference", "observed_history", "mixed"]


def _elicitation_method(request: ValuationExtractionRequest) -> _ElicitationMethod:
    sources: set[_ElicitationMethod] = set()
    if request.comparative_preferences:
        sources.add("interview")
    if request.complaint_texts or request.voice_note_texts:
        sources.add("complaint_inference")
    if request.observed_effort:
        sources.add("observed_history")
    if not sources:
        raise ValueError(
            "ValuationExtractionRequest carries no evidence at all (no complaints, interview "
            "answers, voice notes, or observed history) — nothing to extract"
        )
    if len(sources) > 1:
        return "mixed"
    return next(iter(sources))


class ValuationExtractionAgent:
    """A18 Valuation Extraction. Dependency-injected on a `GeminiClient`
    plus a `GraphWriter`/`IdempotencyStore` pair, wrapped immediately into
    a T3-only `ToolRegistry` and never stored directly on `self` (mirrors
    `StaffPayrollAgent`'s T3-only construction exactly)."""

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
        `StaffPayrollAgent.tool_registry` is — a T4/T5/T6 tool
        registration attempt against this registry must be rejected,
        checkable directly without running the agent."""
        return self._tool_registry

    def extract(self, request: ValuationExtractionRequest) -> ValuationExtractionResult:
        """Extracts and writes one person's `ValuationProfile`.

        Args:
            request: every real evidence source for this person, plus the
                candidate tasks to consider pricing.

        Returns:
            A `ValuationExtractionResult` — `costs` sparse by omission,
            never fabricated (see this module's docstring).

        Raises:
            ValueError: `request` carries no evidence at all.
            errors.ModelResponseMalformed: the model response could not be
                parsed as the expected JSON shape.
            contracts.errors.ToolFailure: the `ValuationProfile` or its
                `VALUATION_OF` edge failed to write.
        """
        elicitation_method = _elicitation_method(request)

        prompt = load_prompt("A18")
        rendered = prompt.text.format(
            person_id=request.person_id,
            candidate_tasks_block=_candidate_tasks_block(request),
            complaint_texts_block=_complaint_texts_block(request),
            comparative_preferences_block=_comparative_preferences_block(request),
            voice_note_texts_block=_voice_note_texts_block(request),
            observed_effort_block=_observed_effort_block(request),
        )
        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.PRO, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)
        raw_items = require_list(parsed, "task_costs", agent_id=AGENT_ID)

        candidate_ids = {str(task_id) for task_id in request.candidate_task_ids}
        costs: dict[str, float] = {}
        reasoning: dict[str, str] = {}
        confidences: list[float] = []

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            task_id = require_str(raw_item, "task_id", agent_id=AGENT_ID)
            if task_id not in candidate_ids:
                continue  # never propagate a hallucinated task id
            cost = require_float(raw_item, "cost", agent_id=AGENT_ID)
            confidence = require_float(raw_item, "confidence", agent_id=AGENT_ID, default=0.0)
            item_reasoning = require_str(raw_item, "reasoning", agent_id=AGENT_ID)

            if confidence < _COST_CONFIDENCE_FLOOR or not math.isfinite(cost) or cost < 0:
                continue  # sparse by omission — never fabricate, never write a low-confidence guess

            costs[task_id] = cost
            reasoning[task_id] = item_reasoning
            confidences.append(confidence)

        omitted_task_ids = tuple(
            task_id for task_id in request.candidate_task_ids if str(task_id) not in costs
        )
        overall_confidence = sum(confidences) / len(confidences) if confidences else 0.0

        profile_id = self._write_valuation_profile(
            request=request, costs=costs, elicitation_method=elicitation_method, confidence=overall_confidence
        )

        return ValuationExtractionResult(
            valuation_profile_id=profile_id,
            person_id=request.person_id,
            costs=costs,
            omitted_task_ids=omitted_task_ids,
            elicitation_method=elicitation_method,
            reasoning=reasoning,
            confidence=overall_confidence,
            model_tier="pro",
            prompt_version=prompt.version,
            invocation_id=uuid.uuid4().hex,
        )

    def _write_valuation_profile(
        self,
        *,
        request: ValuationExtractionRequest,
        costs: dict[str, float],
        elicitation_method: _ElicitationMethod,
        confidence: float,
    ) -> NodeId:
        profile_id = NodeId(f"valuation-profile:{uuid.uuid4().hex}")
        profile = ValuationProfile(
            id=profile_id,
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=confidence,
                deriving_agent=AGENT_ID,
                created_at=datetime.now(UTC),
            ),
            person_id=request.person_id,
            costs=costs,
            elicitation_method=elicitation_method,
        )

        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present

        node_key = IdempotencyKey(
            entity_id=str(request.person_id),
            action_type="write_valuation_profile",
            cycle=request.allocation_cycle_id,
        ).as_str()
        node_result = tool.invoke_idempotent(node_key, operation="write_node", node=profile)
        if not node_result.ok or node_result.value is None:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=node_result.error or "valuation profile write failed",
                retryable=True,
            )
        written_id = NodeId(str(node_result.value))

        edge_key = IdempotencyKey(
            entity_id=str(profile_id),
            action_type="write_valuation_of_edge",
            cycle=request.allocation_cycle_id,
        ).as_str()
        edge = Edge(
            id=EdgeId(f"edge:{uuid.uuid4().hex}"),
            provenance=profile.provenance,
            edge_type=EdgeType.VALUATION_OF,
            from_id=written_id,
            to_id=request.person_id,
        )
        edge_result = tool.invoke_idempotent(edge_key, operation="write_edge", edge=edge)
        if not edge_result.ok:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=edge_result.error or "valuation_of edge write failed",
                retryable=True,
            )
        return written_id


__all__ = ["AGENT_ID", "ValuationExtractionAgent"]
