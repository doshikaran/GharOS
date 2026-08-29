"""A49 — Council Recorder (spec §12.3 Phase 8, §15.9, PHASES.md Phase 12,
ADR-019 Decision 5) — E2's `backend/app/agents/council/`.

*Responsibility:* writes every already-produced Council output permanently
to the graph — one `CouncilPosition` per specialist/delegate/adversary
output (a strict 1:1 wrap, never a summary — spec's design rule 2) plus a
`CONCEDED_BY` edge for every real concession the arbiter's
`CouncilResolution` names. This module holds **no aggregation or synthesis
logic of any kind** — it cannot violate design rule 2 even if misused,
because there is nothing here capable of blending two inputs' content
together; every field on every written `CouncilPosition` is copied
directly from exactly one already-produced object, or is a hardcoded,
structurally-true fact about that object's own kind (see below).

*Model tier:* Deterministic — **no LLM call anywhere in this module**, the
same status as A15 Obligation Writer. `reasoning.gemini_client.
GeminiClient` is never imported by this file at all, so `AgentId("A49")`
cannot even be passed to it by accident.

**What this module does NOT persist (a documented, deliberate scope
decision, not a gap):** `DelegateScoring.valuation_profile` is never
written as its own graph node here. ADR-019 Decision 5 enumerates this
module's writes exhaustively as "one CouncilPosition per specialist/
delegate/adversary output ... plus the arbiter's CONCEDED_BY edges" — no
`ValuationProfile` node write is named there. The delegate's own real cost
data is not discarded, though: every priced branch in `valuation_profile.
costs` is rendered into `CouncilPosition.evidence_refs` verbatim (a
lossless, per-entry format-only transform — `_cost_evidence_refs` below —
never an aggregate or a summary across branches). Flagged for the CTO in
this phase's own report as a candidate follow-up (E4's "visible and
correctable by the person it represents" UI convention for a
`ValuationProfile`, ADR-019 Decision 4, has nothing to read from the graph
today without it), not silently worked around here.

**1:1 wrap discipline, made concrete per input kind — every field below is
either copied verbatim from exactly one input, or a hardcoded fact that is
structurally true of that input's own kind (never an invented judgment):**

- A42-A46 `SpecialistPosition` -> one `CouncilPosition`:
  `held_by_agent=AgentId(position.agent_id)`, `stance=position.stance`
  (copied, never recomputed), `reasoning=position.reasoning` (copied
  verbatim), `evidence_refs=position.evidence_refs` (copied verbatim),
  `branch_id=None` (a specialist's position is a general report, not
  about one single branch — `eliminated_branch_ids` has no field on the
  frozen `CouncilPosition` type to echo onto; that fact remains provable
  through `CouncilResolution.eliminated_branch_ids`, already echoed onto
  the arbiter's own output this module also has in hand).
- A47 `DelegateScoring` -> one `CouncilPosition`:
  `held_by_agent=AgentId("A47")`, `stance="neutral"` (a real, hardcoded
  fact, not an invented opinion: a delegate reports comparative costs, it
  does not itself support or oppose the decision the way a specialist's
  stance does — spec §15.9 gives A47 no stance concept at all),
  `reasoning=scoring.reasoning` (copied verbatim),
  `evidence_refs=_cost_evidence_refs(scoring.valuation_profile)`,
  `branch_id=None` (one delegate's position spans every branch it priced,
  not one).
- A48 `AdversaryAttack` -> exactly one `CouncilPosition`:
  `held_by_agent=AgentId("A48")`, `stance="opposes"` (a real, hardcoded
  fact: attacking a branch **is** opposing it, by A48's own definition —
  spec §15.9 "attacks the leading option" — never an invented judgment),
  `reasoning=attack.critique` (copied verbatim),
  `evidence_refs=tuple(str(oid) for oid in attack.cited_outcome_ids)`
  (real ids, formatted, never fabricated), `branch_id=attack.
  target_branch_id` (the one real branch this attack is actually about).

**`CONCEDED_BY` edges:** one edge (`Decision` -> `Person`) per entry in
`resolution.conceding_person_ids`, reusing `GraphReader.concession_ledger`'s
existing read path unchanged (ADR-019 Decisions 3 and 5) — never a
computed concession beyond what `council_arbiter.resolve()` itself already
decided.

**R4 discipline:** this module never writes to the `Decision` node at all
— it is only ever the `from_id` of a `CONCEDED_BY` edge here, never itself
re-written. `DecisionStatus.RESOLVED` (and indeed `DecisionStatus` itself)
is never imported by this module (see
`backend/tests/test_council_structural_invariants.py`).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from contracts.actions import IdempotencyKey
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    CouncilPosition,
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

from ...tools.graph_write_tool import GraphWriteTool
from ...tools.registry import ToolRegistry
from .json_utils import Stance
from .types import RecorderRequest, RecorderWriteResult

AGENT_ID = AgentId("A49")


def _cost_evidence_refs(profile: ValuationProfile) -> tuple[str, ...]:
    """Every real, priced branch in `profile.costs`, formatted one-to-one
    — sorted by branch id for deterministic output. Never aggregates
    across branches (no sum, no average, no "most expensive" pick) and
    never fabricates an entry for a branch this profile never priced
    (sparse by omission, the same discipline the profile itself already
    carries)."""
    return tuple(f"branch {branch_id}: cost {cost:.4g}" for branch_id, cost in sorted(profile.costs.items()))


def _position_provenance(*, held_by_agent: AgentId) -> Provenance:
    """Every `CouncilPosition` this module writes uses `Derivation.
    AMBIGUOUS` / `source_ref=None` / `confidence=1.0` — the same
    precedent `CouncilConvenerAgent._write_decision` and
    `DecisionFramingAgent._write_decision` establish for a real, held
    position with no single source document to point at (this is a
    synthesis of that agent's own real-time reasoning, not an extraction
    from one document region). `deriving_agent` is the agent that actually
    held this position, never A49 itself — mirrors A15 Obligation
    Writer's `_CONTENT_DERIVING_AGENT` precedent: the mechanical writer is
    never the content's attributed author."""
    return Provenance(
        derivation=Derivation.AMBIGUOUS,
        source_ref=None,
        confidence=1.0,
        deriving_agent=held_by_agent,
        created_at=datetime.now(UTC),
    )


class CouncilRecorderAgent:
    """A49 Council Recorder. Dependency-injected on a `GraphWriter`/
    `IdempotencyStore` pair alone — **no `GeminiClient` parameter exists on
    this class's constructor at all**, unlike every other agent in this
    package, because this module makes no model call, ever."""

    def __init__(self, *, graph_writer: GraphWriter, idempotency_store: IdempotencyStore) -> None:
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T3_INTERNAL_WRITE})
        )
        self._tool_registry.register(
            GraphWriteTool(graph_writer=graph_writer, idempotency_store=idempotency_store)
        )

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed for the same adversarial-proof reason every other
        agent's is — a test can assert this agent holds no tool above T3
        without running it."""
        return self._tool_registry

    def record(self, request: RecorderRequest, *, cycle_id: str) -> RecorderWriteResult:
        """Writes every position and concession in `request` permanently.

        Args:
            request: the decision id plus every already-produced Council
                output for it — nothing here is recomputed or
                reinterpreted.
            cycle_id: identifies this recording round for idempotency (a
                retry with the same `cycle_id` never double-writes).

        Returns:
            A `RecorderWriteResult` naming every real id just written, in
            the order: every specialist position, then every delegate
            position, then the adversary's position.

        Raises:
            contracts.errors.ToolFailure: any write failed.
        """
        tool = self._tool_registry.get("graph_writer")
        assert isinstance(tool, GraphWriteTool)  # registered by this class's own __init__, always present

        position_ids: list[NodeId] = []

        for position in request.specialist_positions:
            position_ids.append(
                self._write_position(
                    tool,
                    decision_id=request.decision_id,
                    held_by_agent=AgentId(position.agent_id),
                    stance=position.stance,
                    branch_id=None,
                    reasoning=position.reasoning,
                    evidence_refs=position.evidence_refs,
                    cycle_id=cycle_id,
                    entity_suffix=f"specialist:{position.agent_id}",
                )
            )

        for scoring in request.delegate_scorings:
            position_ids.append(
                self._write_position(
                    tool,
                    decision_id=request.decision_id,
                    held_by_agent=AgentId("A47"),
                    stance="neutral",
                    branch_id=None,
                    reasoning=scoring.reasoning,
                    evidence_refs=_cost_evidence_refs(scoring.valuation_profile),
                    cycle_id=cycle_id,
                    entity_suffix=f"delegate:{scoring.person_id}",
                )
            )

        attack = request.adversary_attack
        position_ids.append(
            self._write_position(
                tool,
                decision_id=request.decision_id,
                held_by_agent=AgentId("A48"),
                stance="opposes",
                branch_id=attack.target_branch_id,
                reasoning=attack.critique,
                evidence_refs=tuple(str(outcome_id) for outcome_id in attack.cited_outcome_ids),
                cycle_id=cycle_id,
                entity_suffix="adversary:A48",
            )
        )

        conceded_by_edge_ids: list[str] = []
        for person_id in request.resolution.conceding_person_ids:
            conceded_by_edge_ids.append(
                self._write_conceded_by(
                    tool, decision_id=request.decision_id, person_id=person_id, cycle_id=cycle_id
                )
            )

        return RecorderWriteResult(
            position_ids=tuple(position_ids), conceded_by_edge_ids=tuple(conceded_by_edge_ids)
        )

    def _write_position(
        self,
        tool: GraphWriteTool,
        *,
        decision_id: NodeId,
        held_by_agent: AgentId,
        stance: Stance,
        branch_id: NodeId | None,
        reasoning: str,
        evidence_refs: tuple[str, ...],
        cycle_id: str,
        entity_suffix: str,
    ) -> NodeId:
        position = CouncilPosition(
            id=NodeId(f"council-position:{uuid.uuid4().hex}"),
            provenance=_position_provenance(held_by_agent=held_by_agent),
            decision_id=decision_id,
            held_by_agent=held_by_agent,
            stance=stance,
            branch_id=branch_id,
            reasoning=reasoning,
            evidence_refs=evidence_refs,
        )
        key = IdempotencyKey(
            entity_id=f"{decision_id}:{entity_suffix}", action_type="write_council_position", cycle=cycle_id
        ).as_str()
        result = tool.invoke_idempotent(key, operation="write_node", node=position)
        if not result.ok or result.value is None:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=result.error or "council position write failed",
                retryable=True,
            )
        return NodeId(str(result.value))

    def _write_conceded_by(
        self, tool: GraphWriteTool, *, decision_id: NodeId, person_id: NodeId, cycle_id: str
    ) -> str:
        edge = Edge(
            id=EdgeId(f"edge:{uuid.uuid4().hex}"),
            provenance=_position_provenance(held_by_agent=AGENT_ID),
            edge_type=EdgeType.CONCEDED_BY,
            from_id=decision_id,
            to_id=person_id,
        )
        key = IdempotencyKey(
            entity_id=f"{decision_id}:conceded_by:{person_id}",
            action_type="write_conceded_by_edge",
            cycle=cycle_id,
        ).as_str()
        result = tool.invoke_idempotent(key, operation="write_edge", edge=edge)
        if not result.ok or result.value is None:
            raise ToolFailure(
                tool_name="graph_writer",
                reason=result.error or "conceded_by edge write failed",
                retryable=True,
            )
        return str(result.value)


__all__ = ["AGENT_ID", "CouncilRecorderAgent"]
