"""Tests for `app.arbitration.approval_gate.ApprovalGate` — spec §15.12's
Approval Gate service, DEBT-002's actual repayment (ADR-012's three edges
written by real code), and Gate 5's explicit requirements:

- "Approval gate renders complete evidence bundles"
- "Expiry escalates" (never auto-approves)
- "Every action writes audit before executing"
- "Tool failure surfaces as failure — never fabricated success"

Run against the real Firestore emulator throughout (`conftest.py`'s
`writer`/`audit_log`/`idempotency_store` fixtures) — not mocks, per
gharos-standards' "integration tests per subsystem against the Firestore
emulator" rule, since this is squarely the money/safety path (100%
coverage expectation).
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from contracts.actions import ActionResult, EvidenceBundle, RiskTier
from contracts.graph_types import (
    ActionRecord,
    AgentId,
    ApprovalRequest,
    ApprovalStatus,
    EdgeType,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
)
from contracts.tools import PermissionTier

from app.arbitration.approval_gate import ApprovalGate
from app.arbitration.errors import ApprovalRequestNotPending, ArbiterResultNotApprovable
from app.arbitration.gated_tool import ReferenceGatedTool
from app.arbitration.types import ArbiterDecision, ArbiterResult, ProposedAction
from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)
_DEFAULT_TARGET_NODE_ID = NodeId("ledger-event-1")


def _proposed(
    *, action_type: str = "pay_dues", target_node_id: NodeId = _DEFAULT_TARGET_NODE_ID
) -> ProposedAction:
    return ProposedAction(
        action_type=action_type,
        entity_id="due-1",
        cycle="2026-08",
        target_node_id=target_node_id,
        confidence=0.95,
        involves_hard_constraint=False,
        reasoning="Matches last month's dues amount.",
        evidence_consulted=("receipt:doc-1",),
        consequence_if_wrong="Duplicate debit.",
        proposed_by=AgentId("A27"),
        source_ref=None,
    )


def _approve_result(
    *,
    action_type: str = "pay_dues",
    target_node_id: NodeId = _DEFAULT_TARGET_NODE_ID,
    tier: RiskTier = RiskTier.R3_EXPLICIT_APPROVE,
) -> ArbiterResult:
    proposed = _proposed(action_type=action_type, target_node_id=target_node_id)
    return ArbiterResult(
        proposed_action=proposed,
        decision=ArbiterDecision.APPROVE,
        final_risk_tier=tier,
        confidence=0.95,
        evidence_bundle=EvidenceBundle(
            proposed_action=f"{proposed.action_type} ({proposed.entity_id})",
            reasoning=proposed.reasoning,
            evidence_consulted=proposed.evidence_consulted,
            confidence=0.95,
            consequence_if_wrong=proposed.consequence_if_wrong,
        ),
        escalated_to_pro=False,
        discard_reason=None,
    )


def _gate(
    reader: FirestoreGraphReader, writer: FirestoreGraphWriter, audit_log: FirestoreAuditLog
) -> ApprovalGate:
    return ApprovalGate(graph_reader=reader, graph_writer=writer, audit_log=audit_log)


def _tool(
    idempotency_store: FirestoreIdempotencyStore, *, effect: Callable[..., object] | None = None
) -> ReferenceGatedTool:
    return ReferenceGatedTool(
        name="reference_payment_tool",
        tier=PermissionTier.T6_FINANCIAL,
        bounds={},
        effect=effect or (lambda **kwargs: "paid"),
        idempotency_store=idempotency_store,
    )


class TestRequestApprovalWritesEvidenceBundle:
    def test_writes_pending_approval_request_with_complete_evidence_bundle(
        self, writer: FirestoreGraphWriter, audit_log: FirestoreAuditLog, reader: FirestoreGraphReader
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        arbiter_result = _approve_result()

        request = gate.request_approval(arbiter_result, now=NOW)

        assert request.status is ApprovalStatus.PENDING
        assert request.expires_at > NOW
        assert request.risk_tier == "R3"
        assert request.confidence == pytest.approx(0.95)
        stored = reader.get_node(request.id)
        assert isinstance(stored, ApprovalRequest)
        assert stored.status is ApprovalStatus.PENDING
        evidence_keys = (
            "proposed_action",
            "reasoning",
            "evidence_consulted",
            "confidence",
            "consequence_if_wrong",
        )
        for key in evidence_keys:
            assert key in request.evidence_bundle
            assert request.evidence_bundle[key]

    def test_r2_and_r3_get_distinct_ttls(
        self, writer: FirestoreGraphWriter, audit_log: FirestoreAuditLog, reader: FirestoreGraphReader
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        r2 = gate.request_approval(_approve_result(tier=RiskTier.R2_APPROVE), now=NOW)
        r3 = gate.request_approval(_approve_result(tier=RiskTier.R3_EXPLICIT_APPROVE), now=NOW)
        assert r2.expires_at != r3.expires_at
        assert r3.expires_at - NOW == timedelta(hours=12)
        assert r2.expires_at - NOW == timedelta(hours=24)

    def test_non_approve_decision_is_rejected(
        self, writer: FirestoreGraphWriter, audit_log: FirestoreAuditLog, reader: FirestoreGraphReader
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        execute_result = ArbiterResult(
            proposed_action=_proposed(),
            decision=ArbiterDecision.EXECUTE,
            final_risk_tier=RiskTier.R0_SILENT,
            confidence=0.99,
            evidence_bundle=EvidenceBundle("x", "y", (), 0.99, "z"),
            escalated_to_pro=False,
        )
        with pytest.raises(ArbiterResultNotApprovable):
            gate.request_approval(execute_result, now=NOW)


class TestExpiryEscalatesNeverAutoApproves:
    def test_expired_request_becomes_expired_never_approved(
        self, writer: FirestoreGraphWriter, audit_log: FirestoreAuditLog, reader: FirestoreGraphReader
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        request = gate.request_approval(_approve_result(), now=NOW)
        past_expiry = request.expires_at + timedelta(seconds=1)

        refreshed = gate.refresh_status(request, now=past_expiry)

        assert refreshed.status is ApprovalStatus.EXPIRED
        stored = reader.get_node(request.id)
        assert isinstance(stored, ApprovalRequest)
        assert stored.status is ApprovalStatus.EXPIRED

    def test_approve_and_execute_on_an_expired_request_never_executes_the_tool(
        self,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
        reader: FirestoreGraphReader,
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        arbiter_result = _approve_result()
        request = gate.request_approval(arbiter_result, now=NOW)
        past_expiry = request.expires_at + timedelta(seconds=1)

        calls: list[dict[str, object]] = []

        def _effect(**kwargs: object) -> str:
            calls.append(kwargs)
            return "paid"

        tool = _tool(idempotency_store, effect=_effect)
        outcome = gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=request,
            approved_by_person_id=NodeId("person-dad"),
            tool=tool,
            invoke_kwargs={},
            now=past_expiry,
        )

        assert outcome.status == ApprovalStatus.EXPIRED.value
        assert outcome.action_record_id is None
        assert calls == [], "an expired request must never reach the gated tool's effect"
        stored = reader.get_node(request.id)
        assert isinstance(stored, ApprovalRequest)
        assert stored.status is ApprovalStatus.EXPIRED  # not APPROVED

    def test_resolving_an_already_resolved_request_raises(
        self,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
        reader: FirestoreGraphReader,
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        arbiter_result = _approve_result()
        request = gate.request_approval(arbiter_result, now=NOW)
        tool = _tool(idempotency_store)

        gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=request,
            approved_by_person_id=NodeId("person-dad"),
            tool=tool,
            invoke_kwargs={},
            now=NOW,
        )

        with pytest.raises(ApprovalRequestNotPending):
            gate.approve_and_execute(
                arbiter_result=arbiter_result,
                approval_request=request,
                approved_by_person_id=NodeId("person-dad"),
                tool=tool,
                invoke_kwargs={},
                now=NOW,
            )


class TestAuditBeforeExecute:
    def test_audit_record_written_even_when_tool_execution_then_fails(
        self,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
        reader: FirestoreGraphReader,
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        arbiter_result = _approve_result()
        request = gate.request_approval(arbiter_result, now=NOW)

        def _always_fails(**kwargs: object) -> str:
            raise RuntimeError("simulated payment rail outage")

        tool = _tool(idempotency_store, effect=_always_fails)

        outcome = gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=request,
            approved_by_person_id=NodeId("person-dad"),
            tool=tool,
            invoke_kwargs={},
            now=NOW,
        )

        # The action failed -- never fabricated as success.
        assert outcome.action_record_id is None
        tool_result = outcome.tool_result
        assert isinstance(tool_result, ActionResult)
        assert tool_result.ok is False

        # ...but the audit record exists regardless, proving it was written
        # BEFORE execute() ran, not skipped because execution failed.
        all_records = audit_log.all_records()
        matching = [r for r in all_records if r.payload.get("approval_request_id") == str(request.id)]
        assert len(matching) == 1
        assert matching[0].action_type == "pay_dues"


class TestApproveAndExecuteWritesActionRecordAndAdr012Edges:
    def test_success_writes_action_record_and_all_three_new_edges(
        self,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
        reader: FirestoreGraphReader,
    ) -> None:
        from tests.conftest import make_person, make_provenance

        gate = _gate(reader, writer, audit_log)
        target = NodeId("ledger-event-1")
        # neighbours() only resolves edge endpoints for nodes that actually
        # exist in the graph — write real target/approver nodes so ACTS_ON/
        # APPROVED_BY are genuinely walkable, not just present-but-dangling.
        writer.write_node(
            LedgerEvent(
                id=target,
                provenance=make_provenance(),
                kind=LedgerEventKind.DUE,
                amount=500.0,
                currency="INR",
                occurred_at=NOW,
                counterparty_raw="Society Maintenance",
            )
        )
        writer.write_node(make_person("person-dad", "Rohan"))

        arbiter_result = _approve_result(target_node_id=target)
        request = gate.request_approval(arbiter_result, now=NOW)
        tool = _tool(idempotency_store)

        outcome = gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=request,
            approved_by_person_id=NodeId("person-dad"),
            tool=tool,
            invoke_kwargs={"amount": 500},
            now=NOW,
        )

        assert outcome.status == ApprovalStatus.APPROVED.value
        assert outcome.action_record_id is not None
        assert outcome.tool_result.ok is True  # type: ignore[union-attr]

        action_record = reader.get_node(outcome.action_record_id)
        assert isinstance(action_record, ActionRecord)
        assert action_record.approved_by == NodeId("person-dad")
        assert action_record.action_type == "pay_dues"

        # ACTS_ON: ActionRecord -> the real target node it affected (ADR-012).
        acts_on_targets = reader.neighbours(outcome.action_record_id, EdgeType.ACTS_ON)
        assert any(getattr(n, "id", None) == target for n in acts_on_targets)

        # AUTHORIZES: ApprovalRequest -> ActionRecord (ADR-012).
        authorizes_targets = reader.neighbours(request.id, EdgeType.AUTHORIZES)
        assert any(getattr(n, "id", None) == outcome.action_record_id for n in authorizes_targets)

        approved_by_targets = reader.neighbours(request.id, EdgeType.APPROVED_BY)
        assert any(getattr(n, "id", None) == NodeId("person-dad") for n in approved_by_targets)

    def test_approval_request_superseded_to_approved_status(
        self,
        writer: FirestoreGraphWriter,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
        reader: FirestoreGraphReader,
    ) -> None:
        gate = _gate(reader, writer, audit_log)
        arbiter_result = _approve_result()
        request = gate.request_approval(arbiter_result, now=NOW)
        tool = _tool(idempotency_store)

        gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=request,
            approved_by_person_id=NodeId("person-dad"),
            tool=tool,
            invoke_kwargs={},
            now=NOW,
        )

        stored = reader.get_node(request.id)
        assert isinstance(stored, ApprovalRequest)
        assert stored.status is ApprovalStatus.APPROVED


class TestGatedActionRefusesUnapprovedExecution:
    def test_gated_action_constructed_directly_without_approval_refuses_to_run(
        self, idempotency_store: FirestoreIdempotencyStore
    ) -> None:
        """The Gate 5 CTO-review scenario made literal: even constructing
        `GatedAction` directly (bypassing `ApprovalGate` entirely) with a
        non-APPROVED status refuses to execute."""
        from contracts.actions import AuditRef, IdempotencyKey
        from contracts.errors import ApprovalRequired

        from app.arbitration.actions import GatedAction

        tool = _tool(idempotency_store)
        action = GatedAction(
            risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
            idempotency_key=IdempotencyKey(entity_id="due-1", action_type="pay_dues", cycle="2026-08"),
            audit_ref=AuditRef(audit_record_id="fake-audit-1", written_at=NOW),
            tool=tool,
            invoke_kwargs={},
            approval_status=ApprovalStatus.PENDING,
        )
        with pytest.raises(ApprovalRequired):
            action.execute()
