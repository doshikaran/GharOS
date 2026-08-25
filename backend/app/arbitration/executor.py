"""`ActionExecutor` — the R0/R1 (`ArbiterDecision.EXECUTE`) half of "the
only path to action" (spec §15.12), alongside `approval_gate.py`'s R2/R3
(`ArbiterDecision.APPROVE`) half.

R0 ("Silent — execute; log") and R1 ("Notify — execute; notify") actions
never touch the Approval Gate — the Confidence Arbiter's own decision *is*
the authorisation. What still applies unconditionally, exactly as for the
gated path, is audit-before-execute (safety invariant #2/#3): the
`AuditRecord` is durably written before `GraphWriteAction.execute()` is
ever constructed or invoked.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.actions import ActionResult, AuditRef, IdempotencyKey
from contracts.repositories import AuditLog

from app.tools.graph_write_tool import GraphWriteTool

from .actions import GraphWriteAction
from .errors import ArbiterDecisionNotExecutable
from .types import ArbiterDecision, ArbiterResult


class ActionExecutor:
    """Dependency-injected on a `GraphWriteTool` and an `AuditLog` — no
    module-level singleton, per gharos-standards."""

    def __init__(self, *, tool: GraphWriteTool, audit_log: AuditLog) -> None:
        self._tool = tool
        self._audit_log = audit_log

    def execute(
        self, arbiter_result: ArbiterResult, *, invoke_kwargs: dict[str, object]
    ) -> ActionResult[object]:
        """Runs `arbiter_result`'s underlying T3 graph write.

        Raises:
            ArbiterDecisionNotExecutable: `arbiter_result.decision` is not
                `ArbiterDecision.EXECUTE`.
        """
        if arbiter_result.decision is not ArbiterDecision.EXECUTE:
            raise ArbiterDecisionNotExecutable(decision=arbiter_result.decision.value)

        proposed = arbiter_result.proposed_action
        now = datetime.now(UTC)
        audit_record_id = self._audit_log.append(
            action_type=proposed.action_type,
            payload={
                "entity_id": proposed.entity_id,
                "risk_tier": arbiter_result.final_risk_tier.value,
                "proposed_by": str(proposed.proposed_by),
            },
            occurred_at=now,
        )
        audit_ref = AuditRef(audit_record_id=audit_record_id, written_at=datetime.now(UTC))

        action = GraphWriteAction(
            risk_tier=arbiter_result.final_risk_tier,
            idempotency_key=IdempotencyKey(
                entity_id=proposed.entity_id, action_type=proposed.action_type, cycle=proposed.cycle
            ),
            audit_ref=audit_ref,
            tool=self._tool,
            invoke_kwargs=invoke_kwargs,
        )
        return action.execute()


__all__ = ["ActionExecutor"]
