"""Concrete `contracts.actions.Action` implementations — the Command-
pattern objects whose `execute()` actually performs an effect.

**Only code in `backend/app/arbitration/` constructs these.** Per spec
§15.12, the Confidence Arbiter "sits between Layer 3 and Layer 5 and is
the only path to action" — concretely, that means: `ConfidenceArbiter.
evaluate` decides an action should run, and only `approval_gate.py` (for
gated T4/T5/T6 tiers) or a same-package R0/R1 executor ever builds one of
the two classes below and calls `.execute()`. Reasoning agents
(`backend/app/agents/`) construct `app.arbitration.types.ProposedAction`
freely — plain data, no credential — but never an `Action`.

`backend/tests/test_action_construction_boundary.py` proves this
structurally: no module under `backend/app/agents/` imports this module,
and no `GatedAction(`/`GraphWriteAction(` constructor call site exists
anywhere in `backend/app/` outside this package.

Both classes build on `app.audit.write_before_execute.AuditGuardedAction`
(E1, Phase 1) — `execute()` itself is inherited and unmodified (audit-
before-execute is enforced there, structurally, for every subclass);
these classes implement `_perform()` only, per that base class's own
documented extension point.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from contracts.actions import ActionResult, AuditRef, IdempotencyKey, RiskTier
from contracts.errors import ApprovalRequired, ToolFailure
from contracts.graph_types import ApprovalStatus
from contracts.tools import ApprovalGatedTool

from app.audit.write_before_execute import AuditGuardedAction
from app.tools.graph_write_tool import GraphWriteTool


@dataclass(frozen=True, slots=True)
class GraphWriteAction(AuditGuardedAction[object]):
    """A T3-tier (R0/R1 — EXECUTE decision) internal graph write."""

    risk_tier: RiskTier
    idempotency_key: IdempotencyKey
    audit_ref: AuditRef | None
    tool: GraphWriteTool
    invoke_kwargs: Mapping[str, object]

    def _perform(self) -> ActionResult[object]:
        try:
            return self.tool.invoke_idempotent(self.idempotency_key.as_str(), **dict(self.invoke_kwargs))
        except ToolFailure as exc:
            # Tool layer raises; the Action layer converts to the Result-
            # type alternative contracts.actions.Action.execute's own
            # docstring sanctions ("must raise ... (or return
            # ActionResult.failure)") — never re-raised as a bare/
            # uncontextualized exception past this boundary, never
            # reinterpreted as success (safety invariant #7).
            return ActionResult.failure(str(exc))


@dataclass(frozen=True, slots=True)
class GatedAction(AuditGuardedAction[object]):
    """A T4/T5/T6-tier action (APPROVE decision, routed through the
    Approval Gate).

    `_perform()` refuses to run unless `approval_status` is
    `ApprovalStatus.APPROVED` — the structural half of Gate 5's CTO review
    ("try personally to make an agent spend money without approval"): even
    handed this class directly, with a real `audit_ref` already populated,
    it will not execute an unapproved gated action.
    `approval_gate.ApprovalGate.approve_and_execute` is the only sanctioned
    constructor of this class, and only ever passes
    `approval_status=ApprovalStatus.APPROVED` (it has itself just written
    that status to the graph before constructing this action) — any other
    caller supplying a non-APPROVED status is exactly the adversarial case
    `backend/tests/test_approval_gate.py` proves against directly.
    """

    risk_tier: RiskTier
    idempotency_key: IdempotencyKey
    audit_ref: AuditRef | None
    tool: ApprovalGatedTool
    invoke_kwargs: Mapping[str, object]
    approval_status: ApprovalStatus

    def _perform(self) -> ActionResult[object]:
        if self.approval_status is not ApprovalStatus.APPROVED:
            raise ApprovalRequired(action_type=self.tool.name, risk_tier=self.risk_tier.value)
        try:
            return self.tool.invoke_idempotent(self.idempotency_key.as_str(), **dict(self.invoke_kwargs))
        except ToolFailure as exc:
            return ActionResult.failure(str(exc))


__all__ = ["GatedAction", "GraphWriteAction"]
