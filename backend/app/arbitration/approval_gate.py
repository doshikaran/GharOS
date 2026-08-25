"""The Approval Gate (spec §15.12: "Services (not LLM agents)... manages
expiry — expiry escalates, never auto-approves").

Responsibilities:

1. `request_approval` — assembles a `contracts.actions.EvidenceBundle`
   (already built by the Confidence Arbiter) into a graph-resident
   `ApprovalRequest` node, `status=PENDING`, with a real `expires_at`.
2. `refresh_status` — the expiry check. A `PENDING` request whose
   `expires_at` has passed becomes `EXPIRED` (superseded, never mutated in
   place) — **never `APPROVED`.** This is spec §18.2's rule made literal:
   "Approval expiry escalates; never auto-approves." The caller (whichever
   scheduled job or on-demand check calls this) routes an `EXPIRED` result
   to `EscalationAgent`, never treats it as tacit approval.
3. `approve_and_execute` — the only place in this codebase that
   constructs and runs a `GatedAction`. On success, writes the
   `ActionRecord` node plus the three ADR-012 edges (`ACTS_ON`,
   `AUTHORIZES`, `APPROVED_BY`) — this is DEBT-002's actual repayment:
   real code producing real graph structure, not just the contract shape.

**Audit-before-execute is unconditional here**: `AuditLog.append` is
called and durably returns *before* `GatedAction.execute()` is ever
constructed or invoked — so even when the underlying tool then fails, the
audit record already exists (safety invariant #2/#3, proven in
`backend/tests/test_approval_gate.py`).
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import structlog
from contracts.actions import ActionResult, AuditRef, IdempotencyKey, RiskTier
from contracts.graph_types import (
    ActionRecord,
    AgentId,
    ApprovalRequest,
    ApprovalStatus,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Provenance,
)
from contracts.repositories import AuditLog, GraphReader, GraphWriter
from contracts.tools import ApprovalGatedTool

from .actions import GatedAction
from .errors import ApprovalRequestNotPending, ArbiterResultNotApprovable
from .types import ApprovalOutcome, ArbiterDecision, ArbiterResult

logger = structlog.get_logger(__name__)

_APPROVAL_TTL_BY_TIER: dict[RiskTier, timedelta] = {
    RiskTier.R2_APPROVE: timedelta(hours=24),
    RiskTier.R3_EXPLICIT_APPROVE: timedelta(hours=12),
}
"""How long an `ApprovalRequest` stays actionable before it expires and
must be escalated instead. R3 (money) gets a tighter window than R2
(non-financial external communication) — a stale, unreviewed payment
approval is a worse thing to silently sit on than a stale draft-message
approval. Only R2/R3 are covered — `request_approval` is only ever called
for `ArbiterDecision.APPROVE`, which `ConfidenceArbiter` only ever
produces for those two tiers (see `confidence_arbiter._decision_for_tier`)."""

_DEFAULT_TTL = timedelta(hours=24)


def _flatten_evidence_bundle(result: ArbiterResult) -> dict[str, str]:
    bundle = result.evidence_bundle
    return {
        "proposed_action": bundle.proposed_action,
        "reasoning": bundle.reasoning,
        "evidence_consulted": " | ".join(bundle.evidence_consulted),
        "confidence": f"{bundle.confidence:.4f}",
        "consequence_if_wrong": bundle.consequence_if_wrong,
        "escalated_to_pro": str(result.escalated_to_pro),
    }


class ApprovalGate:
    """Dependency-injected on a real `GraphReader`, `GraphWriter`, and
    `AuditLog` — no module-level singleton, per gharos-standards.

    `graph_reader` matters for one specific reason: `approve_and_execute`
    re-reads the *current* `ApprovalRequest` node from the graph by id
    rather than trusting the caller-supplied `approval_request` argument's
    own `status`/`expires_at` fields. A caller holding a stale (or
    deliberately forged) in-memory `ApprovalRequest` claiming `PENDING`
    must not be able to get a second execution — or any execution at all
    on an already-resolved request — out of this method; only the graph's
    own current state decides that (Gate 5 CTO review: "try personally to
    make an agent spend money without approval").
    """

    def __init__(self, *, graph_reader: GraphReader, graph_writer: GraphWriter, audit_log: AuditLog) -> None:
        self._graph_reader = graph_reader
        self._graph_writer = graph_writer
        self._audit_log = audit_log

    def request_approval(
        self, arbiter_result: ArbiterResult, *, now: datetime | None = None
    ) -> ApprovalRequest:
        """Writes a new `PENDING` `ApprovalRequest` node for an
        `ArbiterDecision.APPROVE` result.

        Raises:
            ArbiterResultNotApprovable: `arbiter_result.decision` is not
                `ArbiterDecision.APPROVE`.
        """
        if arbiter_result.decision is not ArbiterDecision.APPROVE:
            raise ArbiterResultNotApprovable(decision=arbiter_result.decision.value)

        current_time = now if now is not None else datetime.now(UTC)
        proposed = arbiter_result.proposed_action
        ttl = _APPROVAL_TTL_BY_TIER.get(arbiter_result.final_risk_tier, _DEFAULT_TTL)

        request = ApprovalRequest(
            id=NodeId(f"approval:{uuid.uuid4().hex}"),
            provenance=Provenance(
                derivation=Derivation.INFERRED if proposed.source_ref is not None else Derivation.AMBIGUOUS,
                source_ref=proposed.source_ref,
                confidence=arbiter_result.confidence,
                deriving_agent=AgentId("A57"),
                created_at=current_time,
            ),
            proposed_action_summary=arbiter_result.evidence_bundle.proposed_action,
            evidence_bundle=_flatten_evidence_bundle(arbiter_result),
            risk_tier=arbiter_result.final_risk_tier.value,
            confidence=arbiter_result.confidence,
            consequence_if_wrong=arbiter_result.evidence_bundle.consequence_if_wrong,
            status=ApprovalStatus.PENDING,
            expires_at=current_time + ttl,
        )
        self._graph_writer.write_node(request)
        logger.info(
            "arbitration.approval_gate.requested",
            approval_request_id=str(request.id),
            action_type=proposed.action_type,
            risk_tier=request.risk_tier,
            expires_at=request.expires_at.isoformat(),
        )
        return request

    def refresh_status(
        self, approval_request: ApprovalRequest, *, now: datetime | None = None
    ) -> ApprovalRequest:
        """Idempotent expiry check. If `approval_request` is `PENDING` and
        `now >= expires_at`, supersedes it to `EXPIRED` and returns the new
        version — **never** to `APPROVED` (spec §18.2: "expiry escalates;
        never auto-approves"). Otherwise returns `approval_request`
        unchanged (including when it is already `EXPIRED`/`APPROVED`/
        `REJECTED` — this method never changes a resolved request).
        """
        current_time = now if now is not None else datetime.now(UTC)
        if approval_request.status is ApprovalStatus.PENDING and current_time >= approval_request.expires_at:
            expired = replace(approval_request, status=ApprovalStatus.EXPIRED)
            self._graph_writer.supersede_node(approval_request.id, expired)
            logger.warning(
                "arbitration.approval_gate.expired",
                approval_request_id=str(approval_request.id),
                expired_at=approval_request.expires_at.isoformat(),
            )
            return expired
        return approval_request

    def approve_and_execute(
        self,
        *,
        arbiter_result: ArbiterResult,
        approval_request: ApprovalRequest,
        approved_by_person_id: NodeId,
        tool: ApprovalGatedTool,
        invoke_kwargs: dict[str, object],
        now: datetime | None = None,
    ) -> ApprovalOutcome:
        """Approves `approval_request` (if still eligible) and executes
        `tool` under it.

        Order of operations, unconditional:
        0. Re-read `approval_request.id` from the graph — the *current*
           node, never the caller-supplied `approval_request` argument's
           own fields (see class docstring).
        1. Refresh expiry — an already-expired request is returned as
           `EXPIRED`, never approved (see `refresh_status`).
        2. Supersede the request to `APPROVED`.
        3. Write the `AuditRecord` (`AuditLog.append`) — **before** any
           attempt to execute the tool.
        4. Construct and execute a `GatedAction` wrapping `tool`.
        5. On a *successful* tool result only: write the `ActionRecord`
           node and the `ACTS_ON` / `AUTHORIZES` / `APPROVED_BY` edges
           (ADR-012).

        Returns:
            An `ApprovalOutcome`. `status == "expired"` if step 1 found
            the request already past `expires_at` (no audit write, no
            execution attempted at all). `status == "approved"` for every
            other path through this method — `action_record_id` and
            `tool_result.ok` distinguish a successful execution from an
            approved-but-failed one; the audit record exists in both
            cases.

        Raises:
            ApprovalRequestNotPending: `approval_request` (after the
                expiry refresh) is not `PENDING` — e.g. already resolved.
                Never raised for the EXPIRED case, which returns a normal
                `ApprovalOutcome` instead (expiry is an expected outcome,
                not a caller bug).
        """
        current_time = now if now is not None else datetime.now(UTC)
        current_node = self._graph_reader.get_node(approval_request.id)
        if not isinstance(current_node, ApprovalRequest):
            raise ApprovalRequestNotPending(approval_request_id=str(approval_request.id), status="not_found")
        refreshed = self.refresh_status(current_node, now=current_time)
        if refreshed.status is ApprovalStatus.EXPIRED:
            return ApprovalOutcome(
                status=ApprovalStatus.EXPIRED.value,
                approval_request_id=refreshed.id,
                action_record_id=None,
                tool_result=None,
            )
        if refreshed.status is not ApprovalStatus.PENDING:
            raise ApprovalRequestNotPending(
                approval_request_id=str(refreshed.id), status=refreshed.status.value
            )

        approved = replace(refreshed, status=ApprovalStatus.APPROVED)
        self._graph_writer.supersede_node(refreshed.id, approved)

        proposed = arbiter_result.proposed_action
        audit_record_id = self._audit_log.append(
            action_type=proposed.action_type,
            payload={
                "approval_request_id": str(approved.id),
                "tool_name": tool.name,
                "tool_tier": tool.tier.value,
                "approved_by": str(approved_by_person_id),
                "entity_id": proposed.entity_id,
            },
            occurred_at=current_time,
        )
        audit_ref = AuditRef(audit_record_id=audit_record_id, written_at=datetime.now(UTC))
        logger.info(
            "arbitration.approval_gate.audited_before_execute",
            approval_request_id=str(approved.id),
            audit_record_id=audit_record_id,
        )

        idempotency_key = IdempotencyKey(
            entity_id=proposed.entity_id, action_type=proposed.action_type, cycle=proposed.cycle
        )
        action = GatedAction(
            risk_tier=arbiter_result.final_risk_tier,
            idempotency_key=idempotency_key,
            audit_ref=audit_ref,
            tool=tool,
            invoke_kwargs=invoke_kwargs,
            approval_status=approved.status,
        )
        result: ActionResult[object] = action.execute()

        if not result.ok:
            logger.warning(
                "arbitration.approval_gate.execution_failed",
                approval_request_id=str(approved.id),
                error=result.error,
            )
            return ApprovalOutcome(
                status=ApprovalStatus.APPROVED.value,
                approval_request_id=approved.id,
                action_record_id=None,
                tool_result=result,
            )

        action_record = ActionRecord(
            id=NodeId(f"action:{uuid.uuid4().hex}"),
            provenance=Provenance(
                derivation=Derivation.INFERRED if proposed.source_ref is not None else Derivation.AMBIGUOUS,
                source_ref=proposed.source_ref,
                confidence=arbiter_result.confidence,
                deriving_agent=proposed.proposed_by,
                created_at=current_time,
            ),
            action_type=proposed.action_type,
            executed_at=current_time,
            approved_by=approved_by_person_id,
        )
        action_record_id = self._graph_writer.write_node(action_record)

        self._graph_writer.write_edge(
            Edge(
                id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                provenance=action_record.provenance,
                edge_type=EdgeType.ACTS_ON,
                from_id=action_record_id,
                to_id=proposed.target_node_id,
            )
        )
        self._graph_writer.write_edge(
            Edge(
                id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                provenance=action_record.provenance,
                edge_type=EdgeType.AUTHORIZES,
                from_id=approved.id,
                to_id=action_record_id,
            )
        )
        self._graph_writer.write_edge(
            Edge(
                id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                provenance=action_record.provenance,
                edge_type=EdgeType.APPROVED_BY,
                from_id=approved.id,
                to_id=approved_by_person_id,
            )
        )

        logger.info(
            "arbitration.approval_gate.executed",
            approval_request_id=str(approved.id),
            action_record_id=str(action_record_id),
        )
        return ApprovalOutcome(
            status=ApprovalStatus.APPROVED.value,
            approval_request_id=approved.id,
            action_record_id=action_record_id,
            tool_result=result,
        )


__all__ = ["ApprovalGate"]
