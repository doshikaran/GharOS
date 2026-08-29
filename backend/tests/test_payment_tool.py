"""Tests for `app.arbitration.payment_tool.SandboxPaymentTool` — Gate 7's
"double payment impossible under replay," proven the same way Gate 5 proved
it for `GraphWriteTool` (`test_graph_write_tool.py`'s
`TestForcedReplayNeverDoubleExecutes`) and integrated end to end through
the real `ApprovalGate` (`test_approval_gate.py`'s established pattern),
against the real Firestore emulator throughout.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from contracts.actions import EvidenceBundle, RiskTier
from contracts.errors import OutOfBounds, ToolFailure
from contracts.graph_types import (
    AgentId,
    ApprovalStatus,
    Derivation,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Provenance,
    RecurringCommitment,
    SourceRef,
)
from contracts.tools import PermissionTier

from app.arbitration.approval_gate import ApprovalGate
from app.arbitration.gated_tool import register_gated_tool
from app.arbitration.payment_tool import PaymentEffect, SandboxPaymentTool
from app.arbitration.types import ArbiterDecision, ArbiterResult, ProposedAction
from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.tools.errors import GatedToolRegistrationDenied
from app.tools.registry import ToolRegistry
from tests._fake_agent_tool_registration import attempt_gated_registration
from tests._fake_idempotency_store import InMemoryIdempotencyStore

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _CountingWriter:
    def __init__(self, real: FirestoreGraphWriter) -> None:
        self._real = real
        self.write_node_calls = 0
        self.supersede_node_calls = 0

    def write_node(self, node: Any) -> NodeId:
        self.write_node_calls += 1
        return self._real.write_node(node)

    def write_edge(self, edge: Any) -> None:
        self._real.write_edge(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        self.supersede_node_calls += 1
        return self._real.supersede_node(old_node_id, new_node)


def _commitment(status: str = "active") -> RecurringCommitment:
    return RecurringCommitment(
        id=NodeId("commitment-gym"),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
            confidence=0.9,
            deriving_agent=AgentId("A3"),
            created_at=NOW,
        ),
        label="Neighbourhood gym membership",
        counterparty="FitZone Gym",
        amount=1500.0,
        cadence="monthly",
        price_history=((NOW - timedelta(days=365), 1200.0),),
        last_used_at=NOW - timedelta(days=90),
        status=status,  # type: ignore[arg-type]
    )


def _debit_kwargs(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "effect": PaymentEffect.DEBIT_PAYMENT.value,
        "amount": 2500.0,
        "currency": "INR",
        "counterparty_raw": "Sunrise Apartments Society",
        "occurred_at": NOW,
        "confidence": 0.95,
        "deriving_agent": "A27",
        "source_ref": None,
    }
    base.update(overrides)
    return base


def _mandate_kwargs(effect: PaymentEffect, **overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "effect": effect.value,
        "commitment_id": "commitment-gym",
        "confidence": 0.9,
        "deriving_agent": "A33",
        "source_ref": None,
    }
    base.update(overrides)
    return base


class TestToolIdentity:
    def test_tier_is_t6(self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore(), bounds={}
        )
        assert tool.tier is PermissionTier.T6_FINANCIAL


class TestDebitPaymentWritesARealLedgerEvent:
    def test_writes_debit_ledger_event(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        result = tool.invoke_idempotent("due-1:pay_dues:2026-08", **_debit_kwargs())

        assert result.ok is True
        written = reader.get_node(NodeId(str(result.value)))
        assert isinstance(written, LedgerEvent)
        assert written.kind is LedgerEventKind.DEBIT
        assert written.amount == 2500.0
        assert written.currency == "INR"


class TestMandateActionsSupersedeTheRealCommitment:
    def test_pause_mandate_sets_status_paused(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        writer.write_node(_commitment())
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )

        result = tool.invoke_idempotent(
            "commitment-gym:pause_mandate:2026-08", **_mandate_kwargs(PaymentEffect.PAUSE_MANDATE)
        )

        assert result.ok is True
        updated = reader.get_node(NodeId(str(result.value)))
        assert isinstance(updated, RecurringCommitment)
        assert updated.status == "paused"
        assert updated.label == "Neighbourhood gym membership", "every other field must be preserved"

    def test_cancel_mandate_sets_status_cancelled(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        writer.write_node(_commitment())
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )

        result = tool.invoke_idempotent(
            "commitment-gym:cancel_mandate:2026-08", **_mandate_kwargs(PaymentEffect.CANCEL_MANDATE)
        )

        updated = reader.get_node(NodeId(str(result.value)))
        assert isinstance(updated, RecurringCommitment)
        assert updated.status == "cancelled"

    def test_unknown_commitment_id_raises_tool_failure(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent(
                "nope:pause_mandate:2026-08",
                **_mandate_kwargs(PaymentEffect.PAUSE_MANDATE, commitment_id="does-not-exist"),
            )


class TestForcedReplayNeverDoubleExecutes:
    """Gate 7's literal requirement: "double payment impossible under
    replay" — same idempotency key twice must never call the underlying
    effect twice, proven by call count against real Firestore-emulator-
    backed writer/reader spies, matching `test_graph_write_tool.py`'s
    established style exactly."""

    def test_second_debit_call_with_same_key_is_a_no_op(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        writer_spy = _CountingWriter(writer)
        tool = SandboxPaymentTool(
            graph_writer=writer_spy, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        key = "due-2:pay_dues:2026-08"

        first = tool.invoke_idempotent(key, **_debit_kwargs())
        second = tool.invoke_idempotent(key, **_debit_kwargs())

        assert first.ok is True
        assert second.value == first.value
        assert writer_spy.write_node_calls == 1, "the underlying writer must be called exactly once"

    def test_second_mandate_call_with_same_key_never_touches_reader_or_writer_again(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        writer.write_node(_commitment())
        writer_spy = _CountingWriter(writer)
        tool = SandboxPaymentTool(
            graph_writer=writer_spy, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        key = "commitment-gym:cancel_mandate:2026-08"

        first = tool.invoke_idempotent(key, **_mandate_kwargs(PaymentEffect.CANCEL_MANDATE))
        # Critically: by now `commitment-gym`'s ORIGINAL version is
        # superseded — `GraphReader.get_node` would return `None` for it
        # (documented "or None if absent/superseded" contract) if the
        # second call attempted to re-read it and rebuild the effect,
        # which would surface as a spurious `ToolFailure` ("commitment not
        # found"), not a clean replay. The idempotency short-circuit must
        # therefore happen BEFORE any read is attempted — this call
        # succeeding at all, with the same result, is itself the proof.
        second = tool.invoke_idempotent(key, **_mandate_kwargs(PaymentEffect.CANCEL_MANDATE))

        assert second.ok is True
        assert second.value == first.value
        assert writer_spy.supersede_node_calls == 1, "a replay must not write to the graph again"

    def test_replay_after_simulated_crash_before_record_result(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        """ "Kill a run mid-flight, restart" (spec §19.1), literally —
        mirrors `test_graph_write_tool.py`'s identically-named test."""
        writer_spy = _CountingWriter(writer)
        key = "due-3:pay_dues:2026-08"

        assert idempotency_store.check_and_reserve(key) is None
        writer_spy.write_node(
            LedgerEvent(
                id=NodeId("ledger-crash-1"),
                provenance=Provenance(
                    derivation=Derivation.AMBIGUOUS,
                    source_ref=None,
                    confidence=0.9,
                    deriving_agent=AgentId("A27"),
                    created_at=NOW,
                ),
                kind=LedgerEventKind.DEBIT,
                amount=2500.0,
                currency="INR",
                occurred_at=NOW,
                counterparty_raw="Sunrise Apartments Society",
            )
        )
        assert writer_spy.write_node_calls == 1

        tool = SandboxPaymentTool(
            graph_writer=writer_spy, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        result = tool.invoke_idempotent(key, **_debit_kwargs())
        assert result.ok is True
        assert writer_spy.write_node_calls == 2

        third = tool.invoke_idempotent(key, **_debit_kwargs())
        assert third.value == result.value
        assert writer_spy.write_node_calls == 2, "once completed, a replay must never call the writer again"


class TestBoundsEnforcement:
    def test_amount_over_max_amount_bound_is_rejected(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer,
            graph_reader=reader,
            idempotency_store=idempotency_store,
            bounds={"max_amount": 1000.0},
        )
        with pytest.raises(OutOfBounds):
            tool.invoke_idempotent("due-4:pay_dues:2026-08", **_debit_kwargs(amount=5000.0))

    def test_amount_at_or_under_max_amount_bound_is_allowed(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer,
            graph_reader=reader,
            idempotency_store=idempotency_store,
            bounds={"max_amount": 5000.0},
        )
        result = tool.invoke_idempotent("due-5:pay_dues:2026-08", **_debit_kwargs(amount=5000.0))
        assert result.ok is True

    def test_exact_match_bound_mismatch_is_rejected(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer,
            graph_reader=reader,
            idempotency_store=idempotency_store,
            bounds={"currency": "USD"},
        )
        with pytest.raises(OutOfBounds):
            tool.invoke_idempotent("due-6:pay_dues:2026-08", **_debit_kwargs(currency="INR"))


class TestNeverFabricatesSuccess:
    def test_unknown_effect_raises_tool_failure(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("due-7:pay_dues:2026-08", effect="refund_everything")

    def test_missing_amount_raises_tool_failure(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        kwargs = _debit_kwargs()
        del kwargs["amount"]
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("due-8:pay_dues:2026-08", **kwargs)

    def test_failed_effect_does_not_record_a_completed_result(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        key = "due-9:pay_dues:2026-08"
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent(
                key, **_mandate_kwargs(PaymentEffect.PAUSE_MANDATE, commitment_id="does-not-exist")
            )
        assert idempotency_store.check_and_reserve(key) is None, "a failure must leave the key retryable"


class TestRegistrationBoundary:
    def test_registration_from_a_mock_agent_side_location_is_rejected(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore(), bounds={}
        )
        registry = ToolRegistry(
            agent_id=AgentId("fake-agent"), allowed_tiers=frozenset({PermissionTier.T6_FINANCIAL})
        )
        with pytest.raises(GatedToolRegistrationDenied) as exc_info:
            attempt_gated_registration(registry, tool)
        assert "app.arbitration" not in exc_info.value.caller_module

    def test_registration_via_register_gated_tool_succeeds(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore(), bounds={}
        )
        registry = ToolRegistry(
            agent_id=AgentId("approval-gate"), allowed_tiers=frozenset({PermissionTier.T6_FINANCIAL})
        )
        register_gated_tool(registry, tool)
        assert registry.has_tier(PermissionTier.T6_FINANCIAL)


class TestEndToEndThroughTheRealApprovalGate:
    """Mirrors `test_approval_gate.py`'s own pattern exactly, with
    `SandboxPaymentTool` in place of `ReferenceGatedTool` — the real proof
    that this tool goes through the exact same audit-before-execute,
    idempotency-keyed, approval-gated path a real payment rail integration
    would use if one existed (this phase's own instructions)."""

    def test_approved_debit_payment_writes_real_graph_structure(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        gate = ApprovalGate(graph_reader=reader, graph_writer=writer, audit_log=audit_log)
        tool = SandboxPaymentTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store, bounds={}
        )
        proposed = ProposedAction(
            action_type="pay_dues",
            entity_id="due-e2e-1",
            cycle="2026-08",
            target_node_id=NodeId("ledger-event-placeholder"),
            confidence=0.95,
            involves_hard_constraint=False,
            reasoning="Matches last month's society dues amount exactly.",
            evidence_consulted=("receipt:doc-1",),
            consequence_if_wrong="Duplicate debit to the society.",
            proposed_by=AgentId("A27"),
            source_ref=None,
        )
        arbiter_result = ArbiterResult(
            proposed_action=proposed,
            decision=ArbiterDecision.APPROVE,
            final_risk_tier=RiskTier.R3_EXPLICIT_APPROVE,
            confidence=0.95,
            evidence_bundle=EvidenceBundle(
                proposed_action="pay_dues (due-e2e-1)",
                reasoning=proposed.reasoning,
                evidence_consulted=proposed.evidence_consulted,
                confidence=0.95,
                consequence_if_wrong=proposed.consequence_if_wrong,
            ),
            escalated_to_pro=False,
            discard_reason=None,
        )

        approval_request = gate.request_approval(arbiter_result, now=NOW)
        assert approval_request.status is ApprovalStatus.PENDING

        outcome = gate.approve_and_execute(
            arbiter_result=arbiter_result,
            approval_request=approval_request,
            approved_by_person_id=NodeId("person-priya"),
            tool=tool,
            invoke_kwargs=_debit_kwargs(),
            now=NOW,
        )

        assert outcome.status == "approved"
        assert outcome.tool_result.ok is True  # type: ignore[union-attr]
        assert outcome.action_record_id is not None

        # Replaying approve_and_execute against a NOW-non-PENDING request
        # must not double-pay — the gate itself refuses (already proven by
        # test_approval_gate.py); this test's own job is only to prove the
        # underlying tool wrote real structure the first time.
        written_event = reader.get_node(NodeId(str(outcome.tool_result.value)))  # type: ignore[union-attr]
        assert isinstance(written_event, LedgerEvent)
        assert written_event.kind is LedgerEventKind.DEBIT
        assert written_event.amount == 2500.0
