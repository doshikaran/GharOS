"""A recording `app.voice.session_manager.ApprovalGateProtocol` test
double — for `test_voice_session_manager.py`'s own direct proof that A62
never calls `approve_and_execute` for an R3-tier intent, no matter what.

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_gemini_fakes.py`/`_fake_idempotency_store.py`'s established
pattern.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from contracts.graph_types import (
    AgentId,
    ApprovalRequest,
    ApprovalStatus,
    Derivation,
    NodeId,
    Provenance,
)
from contracts.tools import ApprovalGatedTool

from app.arbitration.types import ApprovalOutcome, ArbiterResult


class FakeApprovalGate:
    """Records every `request_approval`/`approve_and_execute` call it
    receives and returns a real, well-formed `ApprovalRequest`/
    `ApprovalOutcome` — structurally satisfies `session_manager.
    ApprovalGateProtocol`."""

    def __init__(self) -> None:
        self.request_approval_calls: list[ArbiterResult] = []
        self.approve_and_execute_calls: list[dict[str, object]] = []

    def request_approval(
        self, arbiter_result: ArbiterResult, *, now: datetime | None = None
    ) -> ApprovalRequest:
        self.request_approval_calls.append(arbiter_result)
        current_time = now if now is not None else datetime.now(UTC)
        return ApprovalRequest(
            id=NodeId(f"approval:{uuid.uuid4().hex}"),
            provenance=Provenance(
                derivation=Derivation.AMBIGUOUS,
                source_ref=None,
                confidence=arbiter_result.confidence,
                deriving_agent=AgentId("A57"),
                created_at=current_time,
            ),
            proposed_action_summary=arbiter_result.evidence_bundle.proposed_action,
            evidence_bundle={},
            risk_tier=arbiter_result.final_risk_tier.value,
            confidence=arbiter_result.confidence,
            consequence_if_wrong=arbiter_result.evidence_bundle.consequence_if_wrong,
            status=ApprovalStatus.PENDING,
            expires_at=current_time + timedelta(hours=24),
        )

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
        self.approve_and_execute_calls.append(
            {
                "arbiter_result": arbiter_result,
                "approval_request": approval_request,
                "approved_by_person_id": approved_by_person_id,
                "tool": tool,
                "invoke_kwargs": invoke_kwargs,
            }
        )
        return ApprovalOutcome(
            status=ApprovalStatus.APPROVED.value,
            approval_request_id=approval_request.id,
            action_record_id=NodeId(f"action:{uuid.uuid4().hex}"),
            tool_result=None,
        )


__all__ = ["FakeApprovalGate"]
