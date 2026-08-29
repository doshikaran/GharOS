"""Tests for `app.voice.session_manager.VoiceSessionManager` (A62 — spec
§14.1-§14.6, §15.11, PHASES.md Phase 13, ADR-020 Decision 5).

**This is Gate 13's actual test target.** `TestR3NeverApprovedByVoiceAlone`
is the concrete, direct proof the phase's own dispatch instructions ask
for: construct a `VoiceIntentResult` with `risk_tier=R3_EXPLICIT_APPROVE`
and a `ConfirmationResult(confirmed=True)`, assert no code path reaches
`approve_and_execute`.

Routing tests call `VoiceSessionManager._route`/`_route_gated` directly —
a deliberate choice, not a shortcut: those two methods hold this whole
phase's safety-critical gating logic, and testing them directly (rather
than only indirectly through a full pipeline run) means every case below
is exercised without needing to script real ASR/language/normalisation/
intent-classification JSON responses for cases where the *routing*
decision, not the *classification*, is what's under test. One full,
real, end-to-end pipeline run (`TestFullPipelineHappyPath`) proves the
wiring between every stage genuinely works at least once; state-machine
tests (`TestBargeInAndSilence`) need no pipeline at all.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest
from contracts.actions import ActionResult, RiskTier
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)
from contracts.tools import ApprovalGatedTool, PermissionTier
from google.genai import errors as genai_errors

from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.voice.confirmation_agent import AGENT_ID as A68_AGENT_ID
from app.agents.voice.confirmation_agent import ConfirmationAgent
from app.agents.voice.language_script_identifier_agent import LanguageScriptIdentifierAgent
from app.agents.voice.normalisation_agent import NormalisationAgent
from app.agents.voice.types import ConfirmationResult, VoiceIntentClass, VoiceIntentResult
from app.agents.voice.voice_intent_classifier_agent import (
    AGENT_ID as A67_AGENT_ID,
)
from app.agents.voice.voice_intent_classifier_agent import VoiceIntentClassifierAgent
from app.reasoning import model_router as model_router_module
from app.reasoning.gemini_client import GeminiClient
from app.voice.session_manager import AGENT_ID as A62_AGENT_ID
from app.voice.session_manager import TurnRequest, VoiceSessionManager
from app.voice.session_types import ApprovalContext, GatedExecutionRequest, VoiceRoutingCallbacks
from app.voice.speaker_identification import SpeakerIdentificationAgent
from app.voice.speech_recognition_handler import SpeechRecognitionHandler
from app.voice.tts_client import TtsAudio
from app.voice.types import EnrolledSpeaker, SessionState
from app.voice.voice_response_agent import AGENT_ID as A69_AGENT_ID
from app.voice.voice_response_agent import VoiceResponseAgent

from ._fake_approval_gate import FakeApprovalGate
from ._fake_graph_writer import FakeGraphWriter
from ._fake_raw_payload_store import FakeRawPayloadStore
from ._gemini_fakes import FakeModels, fake_router

_PRO_TIER_AGENTS = {A67_AGENT_ID, A68_AGENT_ID, A69_AGENT_ID}


class _FakeGatedTool(ApprovalGatedTool):
    def __init__(self) -> None:
        self.name = "fake_gated_tool"
        self.tier: PermissionTier = PermissionTier.T4_EXTERNAL_COMMUNICATION
        self.bounds: dict[str, object] = {}
        self.invoked_with: list[dict[str, object]] = []

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        self.invoked_with.append(kwargs)
        return ActionResult.success("done")


class _FakeTtsClient:
    def synthesize(self, *, text: str, voice_name: str, language_code: str) -> TtsAudio:
        return TtsAudio(data=b"\x00\x01", mime_type="audio/L16;codec=pcm;rate=24000")


def _idle_gemini_client() -> GeminiClient:
    """A `GeminiClient` never actually invoked by the direct `_route`
    tests below — wired anyway because `VoiceSessionManager.__init__`
    requires every pipeline-stage dependency to exist."""
    return GeminiClient(router=fake_router(FakeModels(texts=["{}"])))


def _make_manager(
    *,
    monkeypatch: pytest.MonkeyPatch,
    callbacks: VoiceRoutingCallbacks | None = None,
    approval_gate: FakeApprovalGate | None = None,
    silence_timeout: timedelta = timedelta(seconds=8),
) -> tuple[VoiceSessionManager, FakeApprovalGate, FakeGraphWriter]:
    monkeypatch.setattr(
        model_router_module, "PRO_TIER_ALLOWLIST", model_router_module.PRO_TIER_ALLOWLIST | _PRO_TIER_AGENTS
    )
    gemini_client = _idle_gemini_client()
    gate = approval_gate if approval_gate is not None else FakeApprovalGate()
    writer = FakeGraphWriter()
    manager = VoiceSessionManager(
        speech_recognition=SpeechRecognitionHandler(gemini_client=gemini_client),
        speaker_identification=SpeakerIdentificationAgent(gemini_client=gemini_client),
        language_identifier=LanguageScriptIdentifierAgent(gemini_client=gemini_client),
        normalisation=NormalisationAgent(gemini_client=gemini_client),
        entity_resolution=EntityResolutionAgent(gemini_client=gemini_client),
        intent_classifier=VoiceIntentClassifierAgent(gemini_client=gemini_client),
        confirmation=ConfirmationAgent(gemini_client=gemini_client),
        response_agent=VoiceResponseAgent(gemini_client=gemini_client, tts_client=_FakeTtsClient()),
        approval_gate=gate,
        graph_writer=writer,
        raw_payload_store=FakeRawPayloadStore(),
        callbacks=callbacks,
        silence_timeout=silence_timeout,
    )
    return manager, gate, writer


def _intent(
    *,
    intent: VoiceIntentClass,
    risk_tier: RiskTier | None,
    requires_confirmation: bool = False,
    confidence: float = 0.9,
) -> VoiceIntentResult:
    return VoiceIntentResult(
        turn_id="turn-1",
        intent=intent,
        risk_tier=risk_tier,
        target_summary="pay the society maintenance due",
        requires_confirmation=requires_confirmation,
        reasoning="clear household request",
        confidence=confidence,
        model_tier="pro",
        prompt_version="v1",
        invocation_id="inv-1",
        classified_at=datetime.now(UTC),
    )


def _confirmed(confirmed: bool) -> ConfirmationResult:
    return ConfirmationResult(
        turn_id="turn-1",
        confirmed=confirmed,
        reason="matched affirmative" if confirmed else "no match",
        matched_affirmative_phrase="haan kar do" if confirmed else None,
        model_tier="deterministic",
        prompt_version="n/a",
        invocation_id="inv-2",
        evaluated_at=datetime.now(UTC),
    )


def _approval_context() -> ApprovalContext:
    return ApprovalContext(
        action_type="voice_approval",
        entity_id="due-1",
        cycle="2026-08",
        target_node_id=NodeId("ledger-event-1"),
    )


def _known_person(person_id: str = "speaker-1") -> Person:
    """A real, enrolled household member — used by full-pipeline tests
    that need A66 to actually IDENTIFY the speaker (as opposed to the
    zero-enrolled-speakers "unknown speaker" tests, which deliberately
    pass `known_people=()`/`enrolled_speakers=()` instead)."""
    return Person(
        id=NodeId(person_id),
        provenance=Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
            confidence=0.9,
            deriving_agent=AgentId("A0"),
            created_at=datetime.now(UTC),
        ),
        display_name="Priya",
        aliases=(),
        role=PersonRole.ADULT,
        can_drive=True,
        can_sign=True,
        has_bank_access=True,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=LanguageProfile(
            primary_language="hi",
            languages_understood=("hi", "en"),
            script_preference="devanagari",
            code_mixing_profile="hi-en",
            formality_preference="informal",
            literacy_mode=LiteracyMode.BOTH,
        ),
    )


def _enrolled_speaker(person_id: str = "speaker-1") -> EnrolledSpeaker:
    return EnrolledSpeaker(
        person_id=NodeId(person_id),
        display_name="Priya",
        reference_audio=b"\x00\x01" * 20,
        reference_mime_type="audio/L16;rate=16000",
    )


class TestR0R1ExecuteDirectlyNoApprovalGate:
    def test_r0_command_executes_via_callback_and_never_touches_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executed: list[VoiceIntentResult] = []
        manager, gate, _ = _make_manager(
            monkeypatch=monkeypatch,
            callbacks=VoiceRoutingCallbacks(on_command_r0_r1=executed.append),
        )
        intent = _intent(intent=VoiceIntentClass.COMMAND, risk_tier=RiskTier.R0_SILENT)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "executed_r0_r1"
        assert executed == [intent]
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []

    def test_r1_command_executes_via_callback_and_never_touches_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        executed: list[VoiceIntentResult] = []
        manager, gate, _ = _make_manager(
            monkeypatch=monkeypatch,
            callbacks=VoiceRoutingCallbacks(on_command_r0_r1=executed.append),
        )
        intent = _intent(intent=VoiceIntentClass.COMMAND, risk_tier=RiskTier.R1_NOTIFY)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "executed_r0_r1"
        assert executed == [intent]
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []


class TestR2FullVoiceApprovalIsCorrect:
    def test_r2_confirmed_with_gated_execution_approves_and_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R2_APPROVE)
        tool = _FakeGatedTool()
        gated_execution = GatedExecutionRequest(
            tool=tool, invoke_kwargs={"x": 1}, approved_by_person_id=NodeId("person-1")
        )

        outcome = manager._router.route(
            intent,
            confirmation=_confirmed(True),
            approval_context=_approval_context(),
            gated_execution=gated_execution,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "approved_and_executed"
        assert len(gate.request_approval_calls) == 1
        assert len(gate.approve_and_execute_calls) == 1
        assert gate.approve_and_execute_calls[0]["tool"] is tool

    def test_r2_confirmed_without_gated_execution_only_requests_approval(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R2_APPROVE)

        outcome = manager._router.route(
            intent,
            confirmation=_confirmed(True),
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "approval_pending"
        assert len(gate.request_approval_calls) == 1
        assert gate.approve_and_execute_calls == []

    def test_r2_not_confirmed_never_executes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R2_APPROVE)
        tool = _FakeGatedTool()
        gated_execution = GatedExecutionRequest(
            tool=tool, invoke_kwargs={}, approved_by_person_id=NodeId("person-1")
        )

        outcome = manager._router.route(
            intent,
            confirmation=_confirmed(False),
            approval_context=_approval_context(),
            gated_execution=gated_execution,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "approval_pending"
        assert gate.approve_and_execute_calls == []


class TestR3NeverApprovedByVoiceAlone:
    """The concrete, direct proof Gate 13 asks for."""

    def test_r3_confirmed_true_with_gated_execution_still_never_calls_approve_and_execute(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R3_EXPLICIT_APPROVE)
        tool = _FakeGatedTool()
        gated_execution = GatedExecutionRequest(
            tool=tool, invoke_kwargs={"amount": 3500}, approved_by_person_id=NodeId("person-1")
        )

        outcome = manager._router.route(
            intent,
            confirmation=_confirmed(True),  # maximally affirmative
            approval_context=_approval_context(),
            gated_execution=gated_execution,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "approval_pending"
        assert outcome.risk_tier is RiskTier.R3_EXPLICIT_APPROVE
        assert len(gate.request_approval_calls) == 1
        assert gate.approve_and_execute_calls == [], (
            "R3 must never be approved by voice alone, no matter how affirmative the confirmation was"
        )
        assert tool.invoked_with == []

    def test_r3_without_any_confirmation_object_also_never_executes(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R3_EXPLICIT_APPROVE)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "approval_pending"
        assert gate.approve_and_execute_calls == []


class TestR4NeverAutoExecutes:
    def test_decision_trigger_hands_off_to_council_convening_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        triggered: list[VoiceIntentResult] = []
        manager, gate, _ = _make_manager(
            monkeypatch=monkeypatch, callbacks=VoiceRoutingCallbacks(on_decision_trigger=triggered.append)
        )
        intent = _intent(intent=VoiceIntentClass.DECISION_TRIGGER, risk_tier=RiskTier.R4_ESCALATE_ONLY)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "escalated_to_council"
        assert outcome.risk_tier is RiskTier.R4_ESCALATE_ONLY
        assert triggered == [intent]
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []


class TestNonRiskTieredIntentsHandOff:
    def test_capture_hands_off_via_callback_never_touches_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list[VoiceIntentResult] = []
        manager, gate, _ = _make_manager(
            monkeypatch=monkeypatch, callbacks=VoiceRoutingCallbacks(on_capture=captured.append)
        )
        intent = _intent(intent=VoiceIntentClass.CAPTURE, risk_tier=None)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "handed_off"
        assert captured == [intent]
        assert gate.request_approval_calls == []

    def test_query_hands_off_via_callback(self, monkeypatch: pytest.MonkeyPatch) -> None:
        queried: list[VoiceIntentResult] = []
        manager, _, _ = _make_manager(
            monkeypatch=monkeypatch, callbacks=VoiceRoutingCallbacks(on_query=queried.append)
        )
        intent = _intent(intent=VoiceIntentClass.QUERY, risk_tier=None)

        manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert queried == [intent]

    def test_no_callback_wired_does_not_crash(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, _, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.INTENTION, risk_tier=None)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=NodeId("speaker-1"),
        )

        assert outcome.kind == "handed_off"


class TestBargeInAndSilence:
    def test_append_audio_while_listening_just_buffers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, _, _ = _make_manager(monkeypatch=monkeypatch)
        barge_in = manager.append_audio(b"\x00\x01")
        assert barge_in is False
        assert manager.state is SessionState.LISTENING
        assert manager.take_turn_audio() == b"\x00\x01"

    def test_append_audio_while_speaking_is_a_real_barge_in(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, _, _ = _make_manager(monkeypatch=monkeypatch)
        manager.append_audio(b"\x00\x01")
        manager.take_turn_audio()
        manager._state = SessionState.SPEAKING  # simulating "just finished speaking"

        barge_in = manager.append_audio(b"\x02\x03")

        assert barge_in is True
        assert manager.state is SessionState.LISTENING
        assert manager.take_turn_audio() == b"\x02\x03"  # old buffer discarded, not appended to

    def test_check_silence_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        manager, _, _ = _make_manager(monkeypatch=monkeypatch, silence_timeout=timedelta(seconds=5))
        now = datetime.now(UTC)
        manager.note_activity(now=now)
        assert manager.check_silence_timeout(now=now + timedelta(seconds=2)) is False
        assert manager.check_silence_timeout(now=now + timedelta(seconds=6)) is True

    def test_close_resets_state_and_clears_pending_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, _, _ = _make_manager(monkeypatch=monkeypatch)
        manager.append_audio(b"\x00\x01")
        manager.close()
        assert manager.state is SessionState.CLOSED
        assert manager.has_pending_confirmation is False
        assert manager.take_turn_audio() == b""


class TestCorruptedTurnDiscarded:
    def test_a_failed_pipeline_call_discards_the_turn_never_acts_on_it(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            model_router_module,
            "PRO_TIER_ALLOWLIST",
            model_router_module.PRO_TIER_ALLOWLIST | _PRO_TIER_AGENTS,
        )
        failing_client = GeminiClient(
            router=fake_router(
                FakeModels(texts=["{}"], error=genai_errors.APIError(500, {"error": {"message": "down"}}))
            )
        )
        gate = FakeApprovalGate()
        writer = FakeGraphWriter()
        manager = VoiceSessionManager(
            speech_recognition=SpeechRecognitionHandler(gemini_client=failing_client),
            speaker_identification=SpeakerIdentificationAgent(gemini_client=failing_client),
            language_identifier=LanguageScriptIdentifierAgent(gemini_client=failing_client),
            normalisation=NormalisationAgent(gemini_client=failing_client),
            entity_resolution=EntityResolutionAgent(gemini_client=failing_client),
            intent_classifier=VoiceIntentClassifierAgent(gemini_client=failing_client),
            confirmation=ConfirmationAgent(gemini_client=failing_client),
            response_agent=VoiceResponseAgent(gemini_client=failing_client, tts_client=_FakeTtsClient()),
            approval_gate=gate,
            graph_writer=writer,
            raw_payload_store=FakeRawPayloadStore(),
        )

        request = TurnRequest(
            turn_id="turn-x",
            audio=b"\x00\x01",
            audio_mime_type="audio/L16;rate=16000",
            reference_date="2026-08-29",
            known_people=(),
            enrolled_speakers=(),
        )
        result = manager.process_turn(request)

        assert result.kind == "discarded"
        assert result.routing_outcome is None
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []
        assert writer.write_node_calls == 0
        assert manager.has_pending_confirmation is False


class TestNoDependencyIsATrapdoorToArbitration:
    def test_a62_agent_id_is_the_only_agent_id_this_module_declares(self) -> None:
        """A light sanity check that `session_manager.AGENT_ID` is really
        A62, not accidentally a different roster id — the invariant-8
        proof (`test_voice_infra_arbitration_boundary.py`) checks the
        import graph directly; this just guards the identity constant
        itself never silently drifts."""
        assert str(A62_AGENT_ID) == "A62"


def _turn_request(
    *,
    turn_id: str,
    raw_text_hint: str,
    known_people: tuple[Person, ...] = (),
    enrolled_speakers: tuple[EnrolledSpeaker, ...] = (),
) -> TurnRequest:
    """`raw_text_hint` is not actually read by the pipeline (the real ASR
    call decides `raw_text` from the queued fake response) — it exists
    purely so each call site below documents, at a glance, which turn's
    audio this stands in for. `known_people`/`enrolled_speakers` default
    to empty (the "nobody enrolled yet" unknown-speaker case) — pass real
    values for a full-pipeline test that needs A66 to actually identify
    the speaker (e.g. `_known_person()`/`_enrolled_speaker()`)."""
    return TurnRequest(
        turn_id=turn_id,
        audio=f"[audio for: {raw_text_hint}]".encode(),
        audio_mime_type="audio/L16;rate=16000",
        reference_date="2026-08-29",
        known_people=known_people,
        enrolled_speakers=enrolled_speakers,
    )


class TestFullPipelineHappyPath:
    """One full, real, end-to-end pipeline run per case — proves the
    wiring `_process_fresh_turn`/`_process_confirmation_reply` do between
    every real stage genuinely works, not just each stage in isolation."""

    def test_r0_command_completes_in_a_single_turn_no_confirmation(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            model_router_module,
            "PRO_TIER_ALLOWLIST",
            model_router_module.PRO_TIER_ALLOWLIST | _PRO_TIER_AGENTS,
        )
        responses = [
            # 1. A63 ASR
            json.dumps({"raw_text": "turn on the water heater", "tokens": [], "overall_confidence": 0.9}),
            # 2. A64 language identification
            json.dumps(
                {
                    "spans": [
                        {
                            "text": "turn on the water heater",
                            "start_char": 0,
                            "end_char": 25,
                            "language": "en",
                            "confidence": 0.9,
                            "ambiguous_between": [],
                        }
                    ],
                    "overall_confidence": 0.9,
                }
            ),
            # 3. A65 normalisation (Flash pass only — nothing ambiguous)
            json.dumps(
                {
                    "spans": [
                        {
                            "original_text": "turn on the water heater",
                            "normalized_text": "turn on the water heater",
                            "kind": "plain",
                            "language": "en",
                            "start_char": 0,
                            "end_char": 25,
                        }
                    ],
                    "confidence": 0.9,
                }
            ),
            # 4. A67 intent classification
            json.dumps(
                {
                    "intent": "command",
                    "risk_tier": "R0",
                    "target_summary": "turn on the water heater",
                    "reasoning": "a clear, low-stakes household command",
                    "confidence": 0.9,
                    "involves_hard_constraint_name": False,
                    "involves_staff_attendance_or_salary": False,
                }
            ),
            # 5. A69 spoken acknowledgement
            json.dumps({"spoken_text": "Turning on the water heater now.", "confidence": 0.9}),
        ]
        gemini_client = GeminiClient(router=fake_router(FakeModels(texts=responses)))
        executed: list[VoiceIntentResult] = []
        gate = FakeApprovalGate()
        writer = FakeGraphWriter()
        manager = VoiceSessionManager(
            speech_recognition=SpeechRecognitionHandler(gemini_client=gemini_client),
            speaker_identification=SpeakerIdentificationAgent(gemini_client=gemini_client),
            language_identifier=LanguageScriptIdentifierAgent(gemini_client=gemini_client),
            normalisation=NormalisationAgent(gemini_client=gemini_client),
            entity_resolution=EntityResolutionAgent(gemini_client=gemini_client),
            intent_classifier=VoiceIntentClassifierAgent(gemini_client=gemini_client),
            confirmation=ConfirmationAgent(gemini_client=gemini_client),
            response_agent=VoiceResponseAgent(gemini_client=gemini_client, tts_client=_FakeTtsClient()),
            approval_gate=gate,
            graph_writer=writer,
            raw_payload_store=FakeRawPayloadStore(),
            callbacks=VoiceRoutingCallbacks(on_command_r0_r1=executed.append),
        )

        result = manager.process_turn(_turn_request(turn_id="t1", raw_text_hint="turn on the heater"))

        assert result.kind == "completed"
        assert result.raw_text == "turn on the water heater"
        assert result.spoken_response_text == "Turning on the water heater now."
        assert result.response_audio_bytes == b"\x00\x01"
        assert result.routing_outcome is not None
        assert result.routing_outcome.kind == "executed_r0_r1"
        assert len(executed) == 1
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []
        assert writer.write_node_calls == 1

    def test_r2_approval_confirmation_flow_across_two_real_turns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The multi-turn confirmation state machine, exercised for real:
        turn 1 triggers a mandatory read-back (an amount span is present
        — spec §14.6 rule 1); turn 2 is the household member's real
        spoken "haan kar do" reply, which A68 confirms via its real
        structural-then-semantic pipeline, and only THEN does routing
        reach the Approval Gate. Uses a real, enrolled, IDENTIFIED speaker
        (`_known_person`/`_enrolled_speaker`) — an R2 approval from an
        unidentified speaker is refused outright before any of this even
        starts (see `TestUnknownSpeakerRestriction`), so this test's own
        premise (the confirmation flow runs to completion) requires a
        known speaker."""
        monkeypatch.setattr(
            model_router_module,
            "PRO_TIER_ALLOWLIST",
            model_router_module.PRO_TIER_ALLOWLIST | _PRO_TIER_AGENTS,
        )
        responses = [
            # 1. A66 speaker identification — one real comparison against
            #    the single enrolled speaker, confidently matched.
            json.dumps({"same_speaker": True, "confidence": 0.95, "reasoning": "matches enrolled reference"}),
            # 2. A63 ASR (turn 1 — the original request)
            json.dumps(
                {
                    "raw_text": "pay the society maintenance teen hazaar rupee",
                    "tokens": [
                        {"text": "teen hazaar rupee", "start_ms": None, "end_ms": None, "confidence": 0.9}
                    ],
                    "overall_confidence": 0.9,
                }
            ),
            # 2. A64 language identification — tagged "hi" so the household
            #    member's real Hindi affirmative reply ("haan kar do") on
            #    turn 2 is checked against the Hindi affirmative table too
            #    (`affirmatives.check_affirmative` always checks English
            #    plus the read-back's own language).
            json.dumps(
                {
                    "spans": [
                        {
                            "text": "pay the society maintenance teen hazaar rupee",
                            "start_char": 0,
                            "end_char": 46,
                            "language": "hi",
                            "confidence": 0.9,
                            "ambiguous_between": [],
                        }
                    ],
                    "overall_confidence": 0.9,
                }
            ),
            # 4. A65 normalisation — one plain span, one confidently-resolved amount span
            json.dumps(
                {
                    "spans": [
                        {
                            "original_text": "pay the society maintenance",
                            "normalized_text": "pay the society maintenance",
                            "kind": "plain",
                            "language": "en",
                            "start_char": 0,
                            "end_char": 28,
                        },
                        {
                            "original_text": "teen hazaar rupee",
                            "normalized_text": "3000 rupees",
                            "kind": "amount",
                            "language": "hi",
                            "start_char": 29,
                            "end_char": 46,
                            "ambiguous": False,
                            "amount_value": 3000,
                        },
                    ],
                    "confidence": 0.9,
                }
            ),
            # 5. A67 intent classification — APPROVAL, R2
            json.dumps(
                {
                    "intent": "approval",
                    "risk_tier": "R2",
                    "target_summary": "pay ₹3,000 for society maintenance",
                    "reasoning": "a real household approval request",
                    "confidence": 0.9,
                    "involves_hard_constraint_name": False,
                    "involves_staff_attendance_or_salary": False,
                }
            ),
            # 6. A68 generate_readback — must literally contain the digit-grouped amount
            json.dumps(
                {
                    "readback_text": "You want to pay ₹3,000 for society maintenance. Shall I proceed?",
                    "confidence": 0.9,
                }
            ),
            # 7. A69 spoken confirmation prompt
            json.dumps(
                {
                    "spoken_text": "You want to pay ₹3,000 for society maintenance. Shall I proceed?",
                    "confidence": 0.9,
                }
            ),
            # 8. A63 ASR (turn 2 — the household member's real reply)
            json.dumps({"raw_text": "haan kar do", "tokens": [], "overall_confidence": 0.9}),
            # 9. A68 evaluate_response's semantic narrowing pass (only runs because
            #    "haan kar do" matched the canonical affirmative table first)
            json.dumps({"genuinely_affirmative": True, "explanation": "a clear, unqualified affirmative"}),
            # 10. A69 final spoken acknowledgement
            json.dumps({"spoken_text": "Done — paying the society maintenance.", "confidence": 0.9}),
        ]
        gemini_client = GeminiClient(router=fake_router(FakeModels(texts=responses)))
        gate = FakeApprovalGate()
        writer = FakeGraphWriter()
        manager = VoiceSessionManager(
            speech_recognition=SpeechRecognitionHandler(gemini_client=gemini_client),
            speaker_identification=SpeakerIdentificationAgent(gemini_client=gemini_client),
            language_identifier=LanguageScriptIdentifierAgent(gemini_client=gemini_client),
            normalisation=NormalisationAgent(gemini_client=gemini_client),
            entity_resolution=EntityResolutionAgent(gemini_client=gemini_client),
            intent_classifier=VoiceIntentClassifierAgent(gemini_client=gemini_client),
            confirmation=ConfirmationAgent(gemini_client=gemini_client),
            response_agent=VoiceResponseAgent(gemini_client=gemini_client, tts_client=_FakeTtsClient()),
            approval_gate=gate,
            graph_writer=writer,
            raw_payload_store=FakeRawPayloadStore(),
        )

        first = manager.process_turn(
            _turn_request(
                turn_id="t2a",
                raw_text_hint="pay society dues",
                known_people=(_known_person(),),
                enrolled_speakers=(_enrolled_speaker(),),
            )
        )
        assert first.kind == "confirmation_requested"
        assert manager.has_pending_confirmation is True
        assert gate.request_approval_calls == []  # not yet — confirmation isn't resolved

        second = manager.process_turn(_turn_request(turn_id="t2b", raw_text_hint="haan kar do"))

        assert second.kind == "completed"
        assert second.confirmation is not None
        assert second.confirmation.confirmed is True
        assert manager.has_pending_confirmation is False
        assert second.routing_outcome is not None
        assert second.routing_outcome.kind == "approval_pending"  # no GatedExecutionRequest was supplied
        assert len(gate.request_approval_calls) == 1
        assert gate.approve_and_execute_calls == []
        assert writer.write_node_calls == 1


class TestUnknownSpeakerRestriction:
    """spec §15.11 A66's own failure mode: "unknown speaker -> restrict to
    R0/R1 actions only; never accept an approval from an unidentified
    voice." `speaker_person_id=None` is A66's own well-defined "unknown
    speaker" signal (`speaker_identification.py`'s own docstring) — every
    test here constructs that signal directly and proves it is honoured,
    both at the routing layer (`VoiceRouter.route`/`check_speaker_
    authorization`) and, in `test_full_pipeline_...`, at the point in the
    real pipeline where it matters most: BEFORE a confirmation is ever
    offered at all, not merely before execution.
    """

    def test_unknown_speaker_r2_is_refused_and_never_reaches_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R2_APPROVE)
        tool = _FakeGatedTool()
        gated_execution = GatedExecutionRequest(
            tool=tool, invoke_kwargs={"x": 1}, approved_by_person_id=NodeId("person-1")
        )

        outcome = manager._router.route(
            intent,
            confirmation=_confirmed(True),
            approval_context=_approval_context(),
            gated_execution=gated_execution,
            speaker_person_id=None,
        )

        assert outcome.kind == "refused_unknown_speaker"
        assert outcome.risk_tier is RiskTier.R2_APPROVE
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []
        assert tool.invoked_with == []

    def test_unknown_speaker_r3_is_refused_and_never_reaches_approval_gate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The same concrete shape as `TestR3NeverApprovedByVoiceAlone`,
        but for the unknown-speaker gate specifically: a maximally
        affirmative confirmation plus a real `GatedExecutionRequest`
        still never reaches `ApprovalGate.request_approval` OR `.approve_
        and_execute` when the speaker is unidentified."""
        manager, gate, _ = _make_manager(monkeypatch=monkeypatch)
        intent = _intent(intent=VoiceIntentClass.APPROVAL, risk_tier=RiskTier.R3_EXPLICIT_APPROVE)
        tool = _FakeGatedTool()
        gated_execution = GatedExecutionRequest(
            tool=tool, invoke_kwargs={"amount": 3500}, approved_by_person_id=NodeId("person-1")
        )

        outcome = manager._router.route(
            intent,
            confirmation=_confirmed(True),  # maximally affirmative
            approval_context=_approval_context(),
            gated_execution=gated_execution,
            speaker_person_id=None,
        )

        assert outcome.kind == "refused_unknown_speaker"
        assert outcome.risk_tier is RiskTier.R3_EXPLICIT_APPROVE
        assert gate.request_approval_calls == [], (
            "an unidentified speaker must never even reach request_approval for R3, let alone execution"
        )
        assert gate.approve_and_execute_calls == []
        assert tool.invoked_with == []

    def test_unknown_speaker_r4_decision_trigger_is_also_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The coordinator's own instruction is explicit that R4 is
        included in the gate, not just R2/R3 — even convening the Council
        is refused outright from an unidentified speaker."""
        triggered: list[VoiceIntentResult] = []
        manager, gate, _ = _make_manager(
            monkeypatch=monkeypatch, callbacks=VoiceRoutingCallbacks(on_decision_trigger=triggered.append)
        )
        intent = _intent(intent=VoiceIntentClass.DECISION_TRIGGER, risk_tier=RiskTier.R4_ESCALATE_ONLY)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=None,
        )

        assert outcome.kind == "refused_unknown_speaker"
        assert triggered == [], "the Council convening callback must never fire for an unidentified speaker"
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []

    def test_unknown_speaker_r0_command_still_executes_normally(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Spec's own line: restrict *to* R0/R1, not block everything —
        an unidentified speaker's low-stakes command still executes."""
        executed: list[VoiceIntentResult] = []
        manager, gate, _ = _make_manager(
            monkeypatch=monkeypatch, callbacks=VoiceRoutingCallbacks(on_command_r0_r1=executed.append)
        )
        intent = _intent(intent=VoiceIntentClass.COMMAND, risk_tier=RiskTier.R0_SILENT)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=None,
        )

        assert outcome.kind == "executed_r0_r1"
        assert executed == [intent]
        assert gate.request_approval_calls == []

    def test_unknown_speaker_query_still_hands_off_normally(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A read-only query carries no risk tier at all — spec's concern
        is approvals/actions, not answering an informational question."""
        queried: list[VoiceIntentResult] = []
        manager, _, _ = _make_manager(
            monkeypatch=monkeypatch, callbacks=VoiceRoutingCallbacks(on_query=queried.append)
        )
        intent = _intent(intent=VoiceIntentClass.QUERY, risk_tier=None)

        outcome = manager._router.route(
            intent,
            confirmation=None,
            approval_context=_approval_context(),
            gated_execution=None,
            speaker_person_id=None,
        )

        assert outcome.kind == "handed_off"
        assert queried == [intent]

    def test_full_pipeline_unknown_speaker_r2_is_refused_before_any_confirmation_is_offered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The real end-to-end proof: with zero enrolled speakers (A66's
        own genuine "nobody enrolled yet" unknown-speaker path), an R2
        `APPROVAL` intent is refused immediately — this turn completes in
        ONE pass with only 5 queued Gemini responses (ASR, language,
        normalisation, intent, the spoken refusal). If the implementation
        regressed to still offering a read-back/confirmation first (A68's
        `generate_readback`), this test would fail: the 6th call would
        consume the last queued response (A69's own JSON shape, which has
        no `readback_text` key) and raise `ModelResponseMalformed`, which
        `process_turn` does not catch — proving the early short-circuit
        by construction, not merely by asserting the final outcome kind.
        """
        monkeypatch.setattr(
            model_router_module,
            "PRO_TIER_ALLOWLIST",
            model_router_module.PRO_TIER_ALLOWLIST | _PRO_TIER_AGENTS,
        )
        responses = [
            # 1. A63 ASR — no A66 call at all: zero enrolled speakers means
            #    SpeakerIdentificationAgent.identify makes zero comparisons.
            json.dumps(
                {"raw_text": "pay the plumber five thousand rupees", "tokens": [], "overall_confidence": 0.9}
            ),
            # 2. A64 language identification
            json.dumps(
                {
                    "spans": [
                        {
                            "text": "pay the plumber five thousand rupees",
                            "start_char": 0,
                            "end_char": 37,
                            "language": "en",
                            "confidence": 0.9,
                            "ambiguous_between": [],
                        }
                    ],
                    "overall_confidence": 0.9,
                }
            ),
            # 3. A65 normalisation
            json.dumps(
                {
                    "spans": [
                        {
                            "original_text": "pay the plumber five thousand rupees",
                            "normalized_text": "pay the plumber five thousand rupees",
                            "kind": "plain",
                            "language": "en",
                            "start_char": 0,
                            "end_char": 37,
                        }
                    ],
                    "confidence": 0.9,
                }
            ),
            # 4. A67 intent classification — APPROVAL, R2 (would normally
            #    require confirmation — never reached here).
            json.dumps(
                {
                    "intent": "approval",
                    "risk_tier": "R2",
                    "target_summary": "pay the plumber ₹5,000",
                    "reasoning": "a real household approval request",
                    "confidence": 0.9,
                    "involves_hard_constraint_name": False,
                    "involves_staff_attendance_or_salary": False,
                }
            ),
            # 5. A69 spoken refusal — the ONLY response generation call
            #    this turn makes; A68.generate_readback is never reached.
            json.dumps(
                {
                    "spoken_text": "I don't recognize your voice for this — please use the app.",
                    "confidence": 0.9,
                }
            ),
        ]
        gemini_client = GeminiClient(router=fake_router(FakeModels(texts=responses)))
        gate = FakeApprovalGate()
        writer = FakeGraphWriter()
        manager = VoiceSessionManager(
            speech_recognition=SpeechRecognitionHandler(gemini_client=gemini_client),
            speaker_identification=SpeakerIdentificationAgent(gemini_client=gemini_client),
            language_identifier=LanguageScriptIdentifierAgent(gemini_client=gemini_client),
            normalisation=NormalisationAgent(gemini_client=gemini_client),
            entity_resolution=EntityResolutionAgent(gemini_client=gemini_client),
            intent_classifier=VoiceIntentClassifierAgent(gemini_client=gemini_client),
            confirmation=ConfirmationAgent(gemini_client=gemini_client),
            response_agent=VoiceResponseAgent(gemini_client=gemini_client, tts_client=_FakeTtsClient()),
            approval_gate=gate,
            graph_writer=writer,
            raw_payload_store=FakeRawPayloadStore(),
        )

        result = manager.process_turn(
            _turn_request(turn_id="t3", raw_text_hint="pay the plumber, unidentified speaker")
        )

        assert result.kind == "completed"
        assert result.confirmation is None
        assert manager.has_pending_confirmation is False, "no confirmation should ever have been offered"
        assert result.routing_outcome is not None
        assert result.routing_outcome.kind == "refused_unknown_speaker"
        assert gate.request_approval_calls == []
        assert gate.approve_and_execute_calls == []
        assert writer.write_node_calls == 1


__all__: list[str] = []
