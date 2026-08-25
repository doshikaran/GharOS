"""Typed errors local to `backend/app/arbitration/`.

`contracts/errors.py` is frozen and CTO-owned — `ApprovalRequired`,
`ToolFailure`, `OutOfBounds`, and `IdempotencyConflict` from there are
reused directly wherever they apply. The errors below cover failure modes
specific to the approval-request lifecycle that do not fit the frozen
taxonomy (mirrors the precedent `app.agents.consequence.errors` /
`app.persistence.errors` / `app.audit.errors` already set for their own
packages).
"""

from __future__ import annotations


class ArbitrationError(Exception):
    """Base class for every typed error raised by `backend/app/arbitration/`."""


class ApprovalRequestNotPending(ArbitrationError):
    """Raised by `ApprovalGate.approve_and_execute` when the given
    `ApprovalRequest` is not (or is no longer) `ApprovalStatus.PENDING` —
    e.g. a caller attempts to approve a request that was already approved,
    rejected, or (handled separately, never via this error — see
    `approve_and_execute`'s own docstring) expired."""

    def __init__(self, *, approval_request_id: str, status: str) -> None:
        self.approval_request_id = approval_request_id
        self.status = status
        super().__init__(f"approval request {approval_request_id!r} is not pending (status={status!r})")


class ArbiterDecisionNotExecutable(ArbitrationError):
    """Raised by `executor.ActionExecutor.execute` when handed an
    `ArbiterResult` whose `decision` is not `ArbiterDecision.EXECUTE` —
    mirrors `ArbiterResultNotApprovable`'s role for the APPROVE path."""

    def __init__(self, *, decision: str) -> None:
        self.decision = decision
        super().__init__(f"cannot execute a non-EXECUTE arbiter decision: {decision!r}")


class ArbiterResultNotApprovable(ArbitrationError):
    """Raised by `ApprovalGate.request_approval` when handed an
    `ArbiterResult` whose `decision` is not `ArbiterDecision.APPROVE` — the
    Approval Gate only ever mints `ApprovalRequest` nodes for actions the
    Confidence Arbiter actually routed to it; an EXECUTE/ESCALATE/DISCARD
    decision reaching this method is a caller bug, not a normal path."""

    def __init__(self, *, decision: str) -> None:
        self.decision = decision
        super().__init__(f"cannot request approval for a non-APPROVE arbiter decision: {decision!r}")


__all__ = [
    "ApprovalRequestNotPending",
    "ArbiterDecisionNotExecutable",
    "ArbiterResultNotApprovable",
    "ArbitrationError",
]
