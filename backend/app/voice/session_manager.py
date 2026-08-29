"""A62 — Voice Session Manager (spec §14.1-§14.6, §15.11, PHASES.md
Phase 13, ADR-020) — E3's `backend/app/voice/`.

*Responsibility:* owns the inbound-voice session end to end — wake/PTT and
turn-taking state, barge-in, silence timeouts, multi-turn confirmation
context, and clean session close — and is the ONE module in this whole
voice subsystem (this package plus E2's `backend/app/agents/voice/`
combined) that holds an `ApprovalGate` reference (ADR-020 Decision 5 item
3). Drives spec §14.4's real pipeline, in order, per turn:

    A66 (speaker ID) -> A63 (ASR) -> A64 (language/script) -> A65
    (normalise) -> [A5 entity resolution, kinship/name spans only] -> A67
    (intent) -> [A68 read-back + evaluate, only when `requires_
    confirmation`] -> route -> A69 (spoken response) -> SourceDocument
    write.

## The safety-critical piece — this is what Gate 13 actually tests

For a classified `VoiceIntentResult`:

- `risk_tier in {R0, R1}` (`COMMAND` only): executes directly via the
  caller-injected `session_types.VoiceRoutingCallbacks.on_command_r0_r1`
  — **no `ApprovalGate` involved at all** (those tiers' own "execute;
  log/notify" policy, `contracts.actions.RiskTier`).
- `risk_tier is R2_APPROVE` (`APPROVAL` only): after `ConfirmationResult.
  confirmed is True`, this module MAY call `ApprovalGate.
  approve_and_execute` directly — full voice approval end-to-end for R2
  is correct per spec's own table — but only when the caller supplied a
  real `session_types.GatedExecutionRequest` for this turn; otherwise the
  `ApprovalRequest` is written (`request_approval`) and left `PENDING`,
  identical to every other channel with no wired execution path yet.
- `risk_tier is R3_EXPLICIT_APPROVE`: **this module NEVER calls
  `approve_and_execute`, no matter how affirmative `ConfirmationResult`
  is, and regardless of whether a `GatedExecutionRequest` was supplied.**
  Only `request_approval` is ever called; the request is left `PENDING`
  for the existing visual approval queue (Phase 5) to resolve. See
  `routing.VoiceRouter._route_gated` — the branch that calls `approve_
  and_execute` is syntactically reachable only from the R2 arm, not the
  R3 one. Proven directly by `backend/tests/test_voice_session_manager.py
  ::TestR3NeverApprovedByVoiceAlone`.
- `risk_tier is R4_ESCALATE_ONLY` (`DECISION_TRIGGER` only — always,
  structurally, this tier per A67's own guarantee, never taken from the
  model): never auto-executes — hands off to `on_decision_trigger` (the
  Council convening entry point) only. Spec's own words: "voice is the
  entry point, the brief is delivered visually" — this module never
  resolves a decision itself.

`capture` / `intention` / `query` / `correction` carry no risk tier from
A67 (their eventual tier, if any, is decided downstream) — routed via the
matching `VoiceRoutingCallbacks` field, never executed here directly.

## Failure mode: a corrupted or partial turn is discarded, never acted on

Spec's own A62 failure mode: "session corruption -> close cleanly,
re-prompt, never act on a partial turn." `process_turn` catches every
expected pipeline failure (`app.reasoning.errors.GeminiCallFailed`,
`app.agents.voice.errors.ModelResponseMalformed`) at the top level and
returns a `session_types.TurnResult(kind="discarded")` — no code path
from a caught failure reaches `routing.VoiceRouter.route` with partial
data, and `self._pending_confirmation` is unconditionally cleared on a
corrupted confirmation-reply turn too, never left stale.

**The R-tier gating logic itself lives in `routing.py`**, not this file —
see that module's own docstring for why (file-size discipline plus
auditability: Gate 13's whole safety-critical decision point fits in one
small file with nothing else competing for attention). This module owns
pipeline orchestration and multi-turn state; `routing.py` owns the
decision of what to do with a classified intent once this module hands
it one.

*Forbidden:* interpreting content (A64/A65/A67's job) — this module
dispatches only. Legitimately imports `app.arbitration` (indirectly, via
`.routing` — the one deliberate exception in this whole voice subsystem,
per package docstring, alongside `routing.py`/`session_types.py`
themselves); every OTHER module here and in E2's `backend/app/agents/
voice/` does not — see `backend/tests/test_voice_infra_arbitration_
boundary.py` and E2's own `test_voice_agents_arbitration_boundary.py`.

**Stated reason this file still runs past gharos-standards' ~500-line
guideline even after the `routing.py` split:** it wires eight injected
agent dependencies through two genuinely distinct turn-processing paths
(a fresh turn and a confirmation-reply turn) plus a small session state
machine (barge-in, silence timeout, clean close). Each piece is small and
single-purpose on its own; the file is long because the orchestrator's
whole job is *holding all of them together in the right order*, and
splitting the two turn-processing methods into yet another file would
scatter that order across three places instead of clarifying it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from contracts.errors import AmbiguousEntity
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    NodeId,
    Person,
    PersonRole,
    Provenance,
    SourceDocument,
    SourceRef,
)
from contracts.repositories import GraphWriter

from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.voice.confirmation_agent import ConfirmationAgent
from app.agents.voice.language_script_identifier_agent import LanguageScriptIdentifierAgent
from app.agents.voice.normalisation_agent import NormalisationAgent
from app.agents.voice.types import (
    ConfirmationEvaluationRequest,
    LanguageIdentificationRequest,
    NameReference,
    NormalizationRequest,
    NormalizedSpan,
    ReadbackRequest,
    SpeakerLanguageContext,
    VoiceIntentClass,
    VoiceIntentRequest,
)
from app.agents.voice.voice_intent_classifier_agent import VoiceIntentClassifierAgent
from app.persistence.raw_payload_store import RawPayloadStore
from app.reasoning.errors import GeminiCallFailed

from .errors import ConsequentialSpanUnclear
from .pacing import pacing_profile_for
from .routing import ApprovalGateProtocol, VoiceRouter, default_approval_context
from .session_types import (
    ApprovalContext,
    GatedExecutionRequest,
    PendingConfirmation,
    TurnResult,
    VoiceRoutingCallbacks,
    VoiceRoutingOutcome,
)
from .speaker_identification import SpeakerIdentificationAgent
from .speech_recognition_handler import SpeechRecognitionHandler
from .types import EnrolledSpeaker, PacingProfile, ResponseRequest, SessionState, VoiceResponseResult
from .voice_response_agent import VoiceResponseAgent

AGENT_ID = AgentId("A62")
_SESSION_SOURCE_DOCUMENT_CHANNEL = "voice"
_SESSION_SOURCE_DOCUMENT_TYPE = "voice_turn_transcript"
_SESSION_SOURCE_DOCUMENT_REGION = "whole-turn-audio"
"""Not one of the Document-Type Registry's 14 registered types (spec
§5.4) — deliberately, mirroring `app.arbitration.voice_call_tool.py`'s
identical precedent for its own outbound-call transcript: this
`SourceDocument` is written directly by this module, never through the
intake pipeline (A2 never classifies a live voice turn's own transcript)."""

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class TurnRequest:
    """One turn's real input — everything `process_turn` needs."""

    turn_id: str
    audio: bytes
    audio_mime_type: str
    reference_date: str
    known_people: tuple[Person, ...]
    enrolled_speakers: tuple[EnrolledSpeaker, ...]
    noisy_environment: bool = False
    prior_turn_summary: str | None = None
    approval_context: ApprovalContext | None = None
    gated_execution: GatedExecutionRequest | None = None


def _relationship_label(person: Person) -> str:
    """A defensible, honest simplification: this graph carries no
    dedicated kinship-relationship edge yet (spec's 36 edge types have no
    'parent_of'/'sibling_of' member — see `gharos-graph-model`), so the
    read-back's required "name-plus-relationship" (spec §14.6 rule 3) is
    approximated from `PersonRole` rather than a real family-relationship
    graph walk. Stated plainly here, not implied."""
    return person.role.value


class VoiceSessionManager:
    """A62 Voice Session Manager. Owns one inbound-voice session's real
    state and orchestrates every other agent in the inbound pipeline."""

    def __init__(
        self,
        *,
        speech_recognition: SpeechRecognitionHandler,
        speaker_identification: SpeakerIdentificationAgent,
        language_identifier: LanguageScriptIdentifierAgent,
        normalisation: NormalisationAgent,
        entity_resolution: EntityResolutionAgent,
        intent_classifier: VoiceIntentClassifierAgent,
        confirmation: ConfirmationAgent,
        response_agent: VoiceResponseAgent,
        approval_gate: ApprovalGateProtocol,
        graph_writer: GraphWriter,
        raw_payload_store: RawPayloadStore,
        callbacks: VoiceRoutingCallbacks | None = None,
        silence_timeout: timedelta = timedelta(seconds=8),
    ) -> None:
        self._asr = speech_recognition
        self._speaker_id = speaker_identification
        self._language_id = language_identifier
        self._normaliser = normalisation
        self._entity_resolution = entity_resolution
        self._intent_classifier = intent_classifier
        self._confirmation = confirmation
        self._response_agent = response_agent
        self._graph_writer = graph_writer
        self._raw_payload_store = raw_payload_store
        self._router = VoiceRouter(
            approval_gate=approval_gate, callbacks=callbacks or VoiceRoutingCallbacks()
        )
        self._silence_timeout = silence_timeout
        self._pending_confirmation: PendingConfirmation | None = None
        self._last_activity_at: datetime = datetime.now(UTC)
        self._state: SessionState = SessionState.LISTENING
        self._buffer = bytearray()

    @property
    def has_pending_confirmation(self) -> bool:
        return self._pending_confirmation is not None

    @property
    def state(self) -> SessionState:
        return self._state

    def note_activity(self, *, now: datetime | None = None) -> None:
        """Records real activity for silence-timeout purposes — called by
        the caller (`api.voice_router`) on every inbound audio frame."""
        self._last_activity_at = now if now is not None else datetime.now(UTC)

    def check_silence_timeout(self, *, now: datetime | None = None) -> bool:
        """`True` if no activity has been recorded within `silence_
        timeout` — the caller closes the session on this, never auto-acts
        on whatever partial audio may be buffered client-side."""
        current = now if now is not None else datetime.now(UTC)
        return current - self._last_activity_at >= self._silence_timeout

    def append_audio(self, chunk: bytes, *, now: datetime | None = None) -> bool:
        """Buffers one real inbound audio chunk for the turn in progress.

        Implements ADR-020 Decision 3's barge-in rule directly: "a
        barge-in is the client sending new audio frames while
        `session_state == 'speaking'`... reopens a new turn server-side."
        When `state is SPEAKING`, this chunk starts a brand-new turn
        buffer (whatever was previously buffered — there should be
        nothing meaningful mid-playback — is discarded, never appended
        to); state transitions to `LISTENING` either way.

        Returns:
            `True` exactly when this call was a real barge-in (state was
            `SPEAKING` when this chunk arrived).
        """
        self.note_activity(now=now)
        barge_in = self._state is SessionState.SPEAKING
        if barge_in:
            self._buffer = bytearray(chunk)
        else:
            self._buffer.extend(chunk)
        self._state = SessionState.LISTENING
        return barge_in

    def take_turn_audio(self) -> bytes:
        """Pops and clears the current turn's buffered audio — called by
        the caller once it decides a turn has ended (an explicit
        end-of-turn signal or its own silence/VAD detection; neither is
        this module's concern)."""
        audio = bytes(self._buffer)
        self._buffer = bytearray()
        return audio

    def close(self) -> None:
        """Clean session close (spec's own A62 failure mode: a corrupted
        or partial turn is discarded, never acted on) — any pending
        confirmation state and buffered audio is dropped, unconditionally.
        """
        self._pending_confirmation = None
        self._buffer = bytearray()
        self._state = SessionState.CLOSED

    # ------------------------------------------------------------------
    # The per-turn pipeline
    # ------------------------------------------------------------------

    def process_turn(self, request: TurnRequest) -> TurnResult:
        """Processes one real turn end to end. Never raises for an
        expected pipeline failure — every such failure resolves to a
        `TurnResult(kind="discarded")` instead (see module docstring).
        Leaves `state == SPEAKING` on return whenever a real response was
        produced (every path except the rare case where the top-level
        exception itself originated inside response generation) — the
        caller transitions back to `LISTENING` implicitly the next time
        real audio arrives (`append_audio`'s own barge-in handling)."""
        self._state = SessionState.PROCESSING
        try:
            if self._pending_confirmation is not None:
                result = self._process_confirmation_reply(request)
            else:
                result = self._process_fresh_turn(request)
        except ConsequentialSpanUnclear as exc:
            result = self._clarification_result(request, reason=str(exc))
        except (GeminiCallFailed, AmbiguousEntity) as exc:
            logger.warning("voice.session_manager.turn_discarded", turn_id=request.turn_id, reason=str(exc))
            self._pending_confirmation = None
            result = TurnResult(
                turn_id=request.turn_id,
                kind="discarded",
                raw_text=None,
                spoken_response_text=None,
                response_audio_bytes=None,
                response_audio_mime_type=None,
                response_language=None,
                confirmation=None,
                routing_outcome=None,
                discard_reason=str(exc),
            )
        self._state = SessionState.SPEAKING
        return result

    def _process_fresh_turn(self, request: TurnRequest) -> TurnResult:
        speaker_result = self._speaker_id.identify(
            turn_audio=request.audio,
            turn_mime_type=request.audio_mime_type,
            enrolled_speakers=request.enrolled_speakers,
        )
        speaker_person = self._find_person(request.known_people, speaker_result.person_id)
        speaker_context = SpeakerLanguageContext(
            person_id=speaker_result.person_id,
            language_profile=speaker_person.language_profile if speaker_person is not None else None,
        )

        transcription = self._asr.transcribe(
            audio=request.audio, mime_type=request.audio_mime_type, turn_id=request.turn_id
        )

        language_result = self._language_id.identify(
            LanguageIdentificationRequest(
                turn_id=request.turn_id,
                raw_text=transcription.raw_text,
                tokens=transcription.tokens,
                speaker=speaker_context,
            )
        )
        normalization = self._normaliser.normalize(
            NormalizationRequest(
                turn_id=request.turn_id,
                raw_text=transcription.raw_text,
                language_spans=language_result.spans,
                reference_date=request.reference_date,
            )
        )
        dominant_language = language_result.spans[0].language if language_result.spans else "en"

        if normalization.any_needs_clarification:
            reasons = ", ".join(
                span.clarification_reason or "ambiguous amount"
                for span in normalization.spans
                if span.needs_clarification
            )
            return self._clarification_result(request, reason=reasons, language=dominant_language)

        name_references = self._resolve_name_references(request, normalization.spans)

        intent_result = self._intent_classifier.classify(
            VoiceIntentRequest(
                turn_id=request.turn_id,
                raw_text=transcription.raw_text,
                normalized_spans=normalization.spans,
                speaker=speaker_context,
                prior_turn_summary=request.prior_turn_summary,
            )
        )

        # spec §15.11 A66's own failure mode, enforced BEFORE any read-back
        # is even offered — "unknown speaker -> restrict to R0/R1 actions
        # only; never accept an approval from an unidentified voice."
        # Checked here, not only inside `VoiceRouter.route()` itself,
        # because an R2/R3 `APPROVAL` intent always sets `requires_
        # confirmation=True` (see `voice_intent_classifier_agent.py`) —
        # without this early check, an unidentified speaker would still
        # be read a confirmation prompt and asked to confirm before ever
        # reaching `route()`'s own refusal. `routing.VoiceRouter.route`'s
        # own internal call to the same check is defense in depth for the
        # paths that legitimately reach it directly (DECISION_TRIGGER, and
        # the post-confirmation R2/R3 call below).
        speaker_refusal = self._router.check_speaker_authorization(
            intent_result, speaker_person_id=speaker_result.person_id
        )
        if speaker_refusal is not None:
            refusal_message = (
                "I don't recognize your voice, so I can't scan the household mailbox — "
                "that reads private mail. Please identify yourself first, or run it from the app."
                if speaker_refusal.kind == "declined_needs_identification"
                else (
                    "I don't recognize your voice for this kind of request — "
                    "please use the app to approve this."
                )
            )
            response = self._speak(
                turn_id=request.turn_id,
                language=dominant_language,
                content_summary=refusal_message,
                response_kind="error",
                role=None,
                language_profile=speaker_context.language_profile,
                noisy_environment=request.noisy_environment,
            )
            source_document_id = self._write_source_document(
                audio=request.audio, mime_type=request.audio_mime_type, language=dominant_language
            )
            return TurnResult(
                turn_id=request.turn_id,
                kind="completed",
                raw_text=transcription.raw_text,
                spoken_response_text=response.spoken_text,
                response_audio_bytes=response.audio_bytes,
                response_audio_mime_type=response.audio_mime_type,
                response_language=response.language,
                confirmation=None,
                routing_outcome=speaker_refusal,
                source_document_id=source_document_id,
            )

        approval_context = request.approval_context or default_approval_context(
            request.turn_id, intent_result, now=datetime.now(UTC)
        )

        if intent_result.requires_confirmation:
            readback = self._confirmation.generate_readback(
                ReadbackRequest(
                    turn_id=request.turn_id,
                    intent=intent_result,
                    amount_spans=tuple(
                        s for s in normalization.spans if s.kind == "amount" and s.amount_display is not None
                    ),
                    name_references=name_references,
                    date_spans=tuple(s for s in normalization.spans if s.kind == "date"),
                    speaker_language=dominant_language,
                )
            )
            self._pending_confirmation = PendingConfirmation(
                intent_result=intent_result,
                readback=readback,
                approval_context=approval_context,
                gated_execution=request.gated_execution,
                original_audio=request.audio,
                original_audio_mime_type=request.audio_mime_type,
                speaker_person_id=speaker_result.person_id,
                original_language=dominant_language,
            )
            response = self._speak(
                turn_id=request.turn_id,
                language=dominant_language,
                content_summary=readback.readback_text,
                response_kind="confirmation_prompt",
                role=speaker_person.role if speaker_person is not None else None,
                language_profile=speaker_context.language_profile,
                noisy_environment=request.noisy_environment,
            )
            return TurnResult(
                turn_id=request.turn_id,
                kind="confirmation_requested",
                raw_text=transcription.raw_text,
                spoken_response_text=response.spoken_text,
                response_audio_bytes=response.audio_bytes,
                response_audio_mime_type=response.audio_mime_type,
                response_language=response.language,
                confirmation=None,
                routing_outcome=None,
            )

        routing_outcome = self._router.route(
            intent_result,
            confirmation=None,
            approval_context=approval_context,
            gated_execution=None,
            speaker_person_id=speaker_result.person_id,
        )
        is_query = intent_result.intent is VoiceIntentClass.QUERY
        response = self._speak(
            turn_id=request.turn_id,
            language=dominant_language,
            content_summary=intent_result.target_summary,
            response_kind="answer" if is_query else "acknowledgement",
            role=speaker_person.role if speaker_person is not None else None,
            language_profile=speaker_context.language_profile,
            noisy_environment=request.noisy_environment,
        )
        source_document_id = self._write_source_document(
            audio=request.audio, mime_type=request.audio_mime_type, language=dominant_language
        )
        return TurnResult(
            turn_id=request.turn_id,
            kind="completed",
            raw_text=transcription.raw_text,
            spoken_response_text=response.spoken_text,
            response_audio_bytes=response.audio_bytes,
            response_audio_mime_type=response.audio_mime_type,
            response_language=response.language,
            confirmation=None,
            routing_outcome=routing_outcome,
            source_document_id=source_document_id,
        )

    def _process_confirmation_reply(self, request: TurnRequest) -> TurnResult:
        pending = self._pending_confirmation
        assert pending is not None  # guarded by the caller in process_turn
        transcription = self._asr.transcribe(
            audio=request.audio, mime_type=request.audio_mime_type, turn_id=request.turn_id
        )
        confirmation_result = self._confirmation.evaluate_response(
            ConfirmationEvaluationRequest(
                turn_id=request.turn_id,
                readback_text=pending.readback.readback_text,
                spoken_response_text=transcription.raw_text,
                speaker_language=pending.original_language,
            )
        )
        self._pending_confirmation = None

        routing_outcome: VoiceRoutingOutcome | None = None
        if confirmation_result.confirmed:
            routing_outcome = self._router.route(
                pending.intent_result,
                confirmation=confirmation_result,
                approval_context=pending.approval_context,
                gated_execution=pending.gated_execution,
                speaker_person_id=pending.speaker_person_id,
            )
            content_summary = f"Done — {pending.intent_result.target_summary}"
            response_kind = "acknowledgement"
        else:
            content_summary = "Okay, I won't do that."
            response_kind = "acknowledgement"

        response = self._speak(
            turn_id=request.turn_id,
            language=pending.original_language,
            content_summary=content_summary,
            response_kind=response_kind,
            role=None,
            language_profile=None,
            noisy_environment=request.noisy_environment,
        )
        source_document_id = self._write_source_document(
            audio=pending.original_audio,
            mime_type=pending.original_audio_mime_type,
            language=pending.original_language,
        )
        return TurnResult(
            turn_id=request.turn_id,
            kind="completed",
            raw_text=transcription.raw_text,
            spoken_response_text=response.spoken_text,
            response_audio_bytes=response.audio_bytes,
            response_audio_mime_type=response.audio_mime_type,
            response_language=response.language,
            confirmation=confirmation_result,
            routing_outcome=routing_outcome,
            source_document_id=source_document_id,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _find_person(self, known_people: tuple[Person, ...], person_id: NodeId | None) -> Person | None:
        if person_id is None:
            return None
        for person in known_people:
            if person.id == person_id:
                return person
        return None

    def _resolve_name_references(
        self, request: TurnRequest, spans: tuple[NormalizedSpan, ...]
    ) -> tuple[NameReference, ...]:
        references: list[NameReference] = []
        for span in spans:
            if span.kind != "kinship":
                continue
            try:
                result = self._entity_resolution.resolve(
                    mention_text=span.normalized_text,
                    mention_context=span.original_text,
                    known_people=request.known_people,
                    hard_constraint_context=False,
                )
            except AmbiguousEntity:
                continue
            if result.matched_person_id is None:
                continue
            person = self._find_person(request.known_people, result.matched_person_id)
            if person is None:
                continue
            references.append(
                NameReference(
                    display_name=person.display_name,
                    relationship_to_speaker=_relationship_label(person),
                )
            )
        return tuple(references)

    def _clarification_result(self, request: TurnRequest, *, reason: str, language: str = "en") -> TurnResult:
        response = self._speak(
            turn_id=request.turn_id,
            language=language,
            content_summary=f"I didn't quite catch that clearly ({reason}). Could you say that again?",
            response_kind="clarification_request",
            role=None,
            language_profile=None,
            noisy_environment=request.noisy_environment,
        )
        return TurnResult(
            turn_id=request.turn_id,
            kind="needs_clarification",
            raw_text=None,
            spoken_response_text=response.spoken_text,
            response_audio_bytes=response.audio_bytes,
            response_audio_mime_type=response.audio_mime_type,
            response_language=response.language,
            confirmation=None,
            routing_outcome=None,
            discard_reason=reason,
        )

    def _speak(
        self,
        *,
        turn_id: str,
        language: str,
        content_summary: str,
        response_kind: str,
        role: PersonRole | None,
        language_profile: LanguageProfile | None,
        noisy_environment: bool,
    ) -> VoiceResponseResult:
        pacing: PacingProfile = pacing_profile_for(
            language=language,
            role=role,
            noisy_environment=noisy_environment,
            language_profile=language_profile,
        )
        request = ResponseRequest(
            turn_id=turn_id,
            speaker_language=language,
            content_summary=content_summary,
            response_kind=response_kind,  # type: ignore[arg-type]
            pacing=pacing,
        )
        return self._response_agent.respond(request)

    def _write_source_document(self, *, audio: bytes, mime_type: str, language: str) -> NodeId:
        raw_payload_ref = self._raw_payload_store.store(audio, content_type=mime_type)
        doc_id = NodeId(f"doc:{uuid.uuid4().hex}")
        now = datetime.now(UTC)
        document = SourceDocument(
            id=doc_id,
            provenance=Provenance(
                derivation=Derivation.EXTRACTED,
                source_ref=SourceRef(source_document_id=doc_id, region=_SESSION_SOURCE_DOCUMENT_REGION),
                confidence=1.0,
                deriving_agent=AGENT_ID,
                created_at=now,
            ),
            channel=_SESSION_SOURCE_DOCUMENT_CHANNEL,
            raw_payload_ref=raw_payload_ref,
            document_type=_SESSION_SOURCE_DOCUMENT_TYPE,
            ingested_at=now,
            original_language=language,
        )
        return self._graph_writer.write_node(document)


__all__ = ["AGENT_ID", "ApprovalGateProtocol", "TurnRequest", "VoiceSessionManager"]
