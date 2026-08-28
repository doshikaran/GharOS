"""Tests for `app.arbitration.voice_call_tool.VoiceCallTool` — the real T5
outbound-voice tool (PHASES.md Phase 10).

Gate 10's own acceptance list this file's share of: "Approval fires
before any call" (`TestBoundsPrecheckRunsBeforeAnyConversation` — an
out-of-scope `CallBrief` never reaches the conversation engine at all),
"Disclosure on every call, cannot be disabled"
(`TestDisclosureIsAlwaysTrue`), idempotent replay
(`TestForcedReplayNeverPlacesASecondCall`, mirroring
`test_payment_tool.py`'s `TestForcedReplayNeverDoubleExecutes` exactly),
the registration boundary (`TestRegistrationBoundary`, identical shape to
`test_payment_tool.py`'s own), and a real transcript `SourceDocument`
genuinely written (`TestTranscriptIsWritten`), plus an end-to-end proof
through the real `ApprovalGate` (`TestEndToEndThroughTheRealApprovalGate`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from contracts.actions import EvidenceBundle, RiskTier
from contracts.errors import OutOfBounds, ToolFailure
from contracts.graph_types import AgentId, ApprovalStatus, NodeId, SourceDocument
from contracts.tools import PermissionTier

from app.agents.concierge.sandbox_counterparty import SandboxCounterparty
from app.agents.concierge.types import CallBrief, CallOutcomeReport, CounterpartyPersona, CounterpartyVariant
from app.agents.concierge.voice_call_agent import VoiceCallConversationEngine
from app.arbitration.approval_gate import ApprovalGate
from app.arbitration.gated_tool import register_gated_tool
from app.arbitration.types import ArbiterDecision, ArbiterResult, ProposedAction
from app.arbitration.voice_call_tool import VoiceCallTool
from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.persistence.raw_payload_store import LocalFilesystemPayloadStore
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied
from app.tools.registry import ToolRegistry

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

NOW = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
_RANGE_START = datetime(2026, 9, 1, 0, 0, tzinfo=UTC)
_RANGE_END = datetime(2026, 9, 14, 0, 0, tzinfo=UTC)
_FIRST_PREFERRED = datetime(2026, 9, 3, 16, 0, tzinfo=UTC)


@pytest.fixture
def payload_store(tmp_path: Path) -> LocalFilesystemPayloadStore:
    return LocalFilesystemPayloadStore(storage_dir=tmp_path / "raw_payloads")


def _brief(**overrides: object) -> CallBrief:
    base: dict[str, object] = {
        "target_provider_id": NodeId("provider-1"),
        "person_id": NodeId("person-aarav"),
        "objective": "Book a routine dental cleaning for Aarav",
        "date_range": (_RANGE_START, _RANGE_END),
        "price_ceiling": 3000.0,
        "disclosable_facts": ("full name: Aarav Sharma",),
        "must_not_answer": ("bank account number",),
        "preferred_slots": (_FIRST_PREFERRED,),
        "fallback_acceptable": True,
    }
    base.update(overrides)
    return CallBrief(**base)  # type: ignore[arg-type]


def _cooperative_counterparty() -> SandboxCounterparty:
    fake_models = FakeModels(
        texts=[
            '{"utterance": "Yes, Thursday 4pm works.", '
            '"offered_slot_iso": "2026-09-03T16:00:00+00:00", "declines_call": false, '
            '"asks_question": null, "quoted_price": null}'
        ]
    )
    client = GeminiClient(router=fake_router(fake_models))
    persona = CounterpartyPersona(
        variant=CounterpartyVariant.COOPERATIVE,
        clinic_name="Sunrise Dental",
        available_slots=(_FIRST_PREFERRED,),
        out_of_scope_question=None,
    )
    return SandboxCounterparty(gemini_client=client, persona=persona)


def _engine() -> VoiceCallConversationEngine:
    client = GeminiClient(router=fake_router(FakeModels(texts=["Sounds good, thank you."])))
    return VoiceCallConversationEngine(gemini_client=client)


def _report(result: Any) -> CallOutcomeReport:
    """Narrows an `ActionResult[object].value` to a real `CallOutcomeReport`
    for mypy's benefit, mirroring `test_payment_tool.py`'s own
    `isinstance`-assertion style rather than a blanket `type: ignore`."""
    assert isinstance(result.value, CallOutcomeReport)
    return result.value


class _CountingWriter:
    def __init__(self, real: FirestoreGraphWriter) -> None:
        self._real = real
        self.write_node_calls = 0

    def write_node(self, node: Any) -> NodeId:
        self.write_node_calls += 1
        return self._real.write_node(node)

    def write_edge(self, edge: Any) -> None:
        self._real.write_edge(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        return self._real.supersede_node(old_node_id, new_node)


class TestToolIdentity:
    def test_tier_is_t5(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        assert tool.tier is PermissionTier.T5_VOICE_OUTBOUND


class TestBoundsPrecheckRunsBeforeAnyConversation:
    """Gate 10: "Approval fires before any call" — proven directly: an
    out-of-scope `CallBrief` is rejected before `run_conversation` is ever
    invoked (proven via a counterparty whose fake Gemini client would
    raise if ever called at all)."""

    def _never_call_counterparty(self) -> SandboxCounterparty:
        fake_models = FakeModels(texts=["irrelevant"], error=RuntimeError("must never be called"))
        client = GeminiClient(router=fake_router(fake_models))
        persona = CounterpartyPersona(
            variant=CounterpartyVariant.COOPERATIVE,
            clinic_name="Sunrise Dental",
            available_slots=(_FIRST_PREFERRED,),
            out_of_scope_question=None,
        )
        return SandboxCounterparty(gemini_client=client, persona=persona)

    def test_wrong_target_provider_id_is_rejected_before_any_call(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={"target_provider_id": "provider-approved"},
        )
        with pytest.raises(OutOfBounds):
            tool.invoke_idempotent(
                "call-1", brief=_brief(target_provider_id=NodeId("provider-different")),
                counterparty=self._never_call_counterparty(),
            )

    def test_price_ceiling_over_the_approved_max_is_rejected_before_any_call(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={"price_ceiling_max": 2000.0},
        )
        with pytest.raises(OutOfBounds):
            tool.invoke_idempotent(
                "call-2", brief=_brief(price_ceiling=5000.0), counterparty=self._never_call_counterparty()
            )

    def test_date_range_wider_than_approved_is_rejected_before_any_call(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={"date_range": (_RANGE_START, _RANGE_END)},
        )
        wider = (_RANGE_START - timedelta(days=5), _RANGE_END)
        with pytest.raises(OutOfBounds):
            tool.invoke_idempotent(
                "call-3", brief=_brief(date_range=wider), counterparty=self._never_call_counterparty()
            )

    def test_a_brief_within_every_bound_is_allowed_through(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={
                "target_provider_id": "provider-1",
                "price_ceiling_max": 3000.0,
                "date_range": (_RANGE_START, _RANGE_END),
            },
        )
        result = tool.invoke_idempotent("call-4", brief=_brief(), counterparty=_cooperative_counterparty())
        assert result.ok is True


class TestDisclosureIsAlwaysTrue:
    def test_disclosure_given_is_always_true_on_a_successful_call(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        result = tool.invoke_idempotent("call-5", brief=_brief(), counterparty=_cooperative_counterparty())
        assert result.ok is True
        assert _report(result).disclosure_given is True


class TestTranscriptIsWritten:
    def test_transcript_source_document_is_a_real_graph_node(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        result = tool.invoke_idempotent("call-6", brief=_brief(), counterparty=_cooperative_counterparty())
        assert result.ok is True
        report = _report(result)
        node = reader.get_node(report.transcript_source_document_id)
        assert isinstance(node, SourceDocument)
        assert node.channel == "voice_call_outbound"
        assert node.document_type == "voice_call_transcript"

        stored_bytes = payload_store.retrieve(node.raw_payload_ref)
        transcript_text = stored_bytes.decode("utf-8")
        assert "automated assistant" in transcript_text
        assert "caller" in transcript_text
        assert "counterparty" in transcript_text


class TestForcedReplayNeverPlacesASecondCall:
    def test_second_call_with_same_key_is_a_no_op(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        writer_spy = _CountingWriter(writer)
        idempotency_store = InMemoryIdempotencyStore()
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer_spy,
            raw_payload_store=payload_store,
            idempotency_store=idempotency_store,
            bounds={},
        )
        key = "call-7"

        first = tool.invoke_idempotent(key, brief=_brief(), counterparty=_cooperative_counterparty())
        assert writer_spy.write_node_calls == 1
        second = tool.invoke_idempotent(key, brief=_brief(), counterparty=_cooperative_counterparty())

        assert first.ok is True
        assert second.ok is True
        first_report, second_report = _report(first), _report(second)
        assert second_report.call_id == first_report.call_id
        assert second_report.transcript_source_document_id == first_report.transcript_source_document_id
        assert writer_spy.write_node_calls == 1, "the underlying writer must be called exactly once"

    def test_replay_returns_a_full_call_outcome_report_not_a_bare_string(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        idempotency_store = InMemoryIdempotencyStore()
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=idempotency_store,
            bounds={},
        )
        key = "call-8"
        tool.invoke_idempotent(key, brief=_brief(), counterparty=_cooperative_counterparty())
        second = tool.invoke_idempotent(key, brief=_brief(), counterparty=_cooperative_counterparty())
        second_report = _report(second)
        assert second_report.claimed_slot == _FIRST_PREFERRED
        assert second_report.disclosure_given is True


class TestNeverFabricatesSuccess:
    def test_missing_brief_raises_tool_failure(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("call-9", counterparty=_cooperative_counterparty())

    def test_missing_counterparty_raises_tool_failure(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("call-10", brief=_brief())

    def test_failed_effect_does_not_record_a_completed_result(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        idempotency_store = InMemoryIdempotencyStore()
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=idempotency_store,
            bounds={},
        )
        key = "call-11"
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent(key, brief=_brief())
        assert idempotency_store.check_and_reserve(key) is None, "a failure must leave the key retryable"


class TestRegistrationBoundary:
    def test_registration_from_a_mock_agent_side_location_is_rejected(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        registry = ToolRegistry(
            agent_id=AgentId("fake-agent"), allowed_tiers=frozenset({PermissionTier.T5_VOICE_OUTBOUND})
        )
        with pytest.raises(GatedToolRegistrationDenied) as exc_info:
            attempt_gated_registration(registry, tool)
        assert "app.arbitration" not in exc_info.value.caller_module

    def test_registration_via_register_gated_tool_succeeds(
        self, writer: FirestoreGraphWriter, payload_store: LocalFilesystemPayloadStore
    ) -> None:
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        registry = ToolRegistry(
            agent_id=AgentId("approval-gate"), allowed_tiers=frozenset({PermissionTier.T5_VOICE_OUTBOUND})
        )
        register_gated_tool(registry, tool)
        assert registry.has_tier(PermissionTier.T5_VOICE_OUTBOUND)


class TestEndToEndThroughTheRealApprovalGate:
    def test_approved_call_writes_real_graph_structure(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        audit_log: FirestoreAuditLog,
        idempotency_store: FirestoreIdempotencyStore,
        payload_store: LocalFilesystemPayloadStore,
    ) -> None:
        gate = ApprovalGate(graph_reader=reader, graph_writer=writer, audit_log=audit_log)
        tool = VoiceCallTool(
            conversation_engine=_engine(),
            graph_writer=writer,
            raw_payload_store=payload_store,
            idempotency_store=idempotency_store,
            bounds={},
        )
        proposed = ProposedAction(
            action_type="place_outbound_call",
            entity_id="call-e2e-1",
            cycle="2026-09",
            target_node_id=NodeId("provider-1"),
            confidence=0.9,
            involves_hard_constraint=False,
            reasoning="Household requested a dentist booking; provider ranked #1.",
            evidence_consulted=("provider_ranking:provider-1",),
            consequence_if_wrong="An unwanted call is placed.",
            proposed_by=AgentId("A53"),
            source_ref=None,
        )
        arbiter_result = ArbiterResult(
            proposed_action=proposed,
            decision=ArbiterDecision.APPROVE,
            final_risk_tier=RiskTier.R2_APPROVE,
            confidence=0.9,
            evidence_bundle=EvidenceBundle(
                proposed_action="place_outbound_call (call-e2e-1)",
                reasoning=proposed.reasoning,
                evidence_consulted=proposed.evidence_consulted,
                confidence=0.9,
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
            invoke_kwargs={"brief": _brief(), "counterparty": _cooperative_counterparty()},
            now=NOW,
        )

        assert outcome.status == "approved"
        assert outcome.tool_result.ok is True  # type: ignore[union-attr]
        assert outcome.action_record_id is not None

        report = outcome.tool_result.value  # type: ignore[union-attr]
        written_doc = reader.get_node(report.transcript_source_document_id)
        assert isinstance(written_doc, SourceDocument)
