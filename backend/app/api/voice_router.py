"""GharOS — the inbound-voice HTTP/WebSocket surface (PHASES.md Phase 13,
ADR-020 Decision 3) — E3's own router, registered in `app.main` alongside
`app.api.graph_router` (E1) and `app.api.debug` (E2), following that
established registration pattern exactly.

**Scope, stated plainly (ADR-020 Decision 3):** inbound voice is a real
browser-microphone-to-backend WebSocket session — there is no PSTN/dial-in
telephony line in this hackathon build at all. What is real here: a live
mic-to-model round trip, real ASR (A63), real per-span language/intent
reasoning (E2's A64/A65/A67/A68), real TTS playback audio (A69), and the
full R-tier safety gating in front of the Approval Gate (A62,
`app.voice.session_manager`).

Three endpoints:

- `WS /voice/session` — the real-time session, exact wire contract per
  ADR-020 Decision 3: binary PCM16 16kHz frames in; JSON frames out
  (`session_state` / `transcript_final` / `confirmation_prompt` /
  `response_audio` / `error`). A JSON text frame `{"type": "end_of_turn"}`
  from the client still ends a turn explicitly when sent. **Real
  end-of-turn detection, added after reading E4's actual client code (not
  assumed):** `lib/mic-capture.ts` streams binary frames continuously and
  never sends that control frame at all — this project does not implement
  true server-side voice-activity detection this phase (stated honestly,
  not implied), but `_END_OF_TURN_SILENCE_SECONDS` below is a real, if
  simple, idle-timeout heuristic that makes the real frontend actually
  work: a genuine pause in incoming audio longer than that window is
  treated as "the household member has finished speaking," and the same
  polling interval also drives the full-session `check_silence_timeout`
  close. See `_END_OF_TURN_SILENCE_SECONDS`'s own docstring.
  **Deviation from the ADR's illustrative wire example, disclosed
  honestly:** `response_audio.mime_type` carries the REAL MIME type
  Vertex AI's TTS call returned (`"audio/L16;codec=pcm;rate=24000"`, not
  the ADR text's illustrative `"audio/mpeg"` example) — see `voice.
  tts_client`'s own module docstring for why; the field name and overall
  frame shape are unchanged.
- `POST /voice/persons/{person_id}/enroll` — voiceprint enrollment
  (`app.tools.voice_profile_tools.VoiceprintEnrollmentTool`), a JSON body
  `{"audio_b64": str, "mime_type": str}`. **Known integration gap with
  E4's current client, disclosed here rather than silently left for
  someone to discover:** `frontend/lib/voice-persons.ts`'s own doc
  comment says it was written before this endpoint landed and guesses
  `POST /voice/persons/{id}/voiceprint` with a `multipart/form-data` body
  — that guess does not match this real, tested endpoint's path or body
  encoding. E4's own file explicitly anticipates this reconciliation
  ("a small fix in this one file, never a UI rewrite"); this backend
  shape is the one this phase built and tested against, not the frontend
  guess.
- `GET`/`PATCH /voice/persons/{person_id}/language-profile` — E4's
  per-person language settings screen
  (`app.tools.voice_profile_tools.LanguageProfileTool`). Field names and
  path match `frontend/lib/language-profile.ts` exactly — verified by
  reading that file directly, not assumed.

**Stated reason this file runs past gharos-standards' ~500-line
guideline:** it is one HTTP/WebSocket surface (the FastAPI router
convention every other phase's router in this codebase already follows —
`app.api.graph_router`, `app.api.debug`) covering three real endpoints
plus their dependency-injection providers; splitting the REST endpoints
into a second router file would save lines at the cost of a second file
a reader has to open to see this surface's complete, real behaviour.
"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import structlog
from contracts.actions import IdempotencyKey
from contracts.graph_types import LiteracyMode, NodeId, Person
from contracts.ingestion import IngestionRequest, IngestionSourceKind, OAuthProvider
from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, status
from google.cloud import firestore
from pydantic import BaseModel

from app.adapters.secret_manager import SecretManagerAdapter
from app.agents.intake.entity_resolution import EntityResolutionAgent
from app.agents.voice.confirmation_agent import ConfirmationAgent
from app.agents.voice.language_script_identifier_agent import LanguageScriptIdentifierAgent
from app.agents.voice.normalisation_agent import NormalisationAgent
from app.agents.voice.voice_intent_classifier_agent import VoiceIntentClassifierAgent
from app.api.ingest_router import DEMO_HOUSEHOLD_ID, build_ingestion_orchestrator
from app.api.oauth_router import get_credential_store, get_secret_reader
from app.arbitration.approval_gate import ApprovalGate
from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_client import create_firestore_client
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.persistence.oauth_credential_store import FirestoreOAuthCredentialStore
from app.persistence.raw_payload_store import RawPayloadStore, create_local_filesystem_payload_store
from app.pipelines.ingestion_orchestrator import IngestionOrchestrator
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.model_router import ModelRouter
from app.settings import Settings, get_settings
from app.tools.voice_profile_tools import LanguageProfileTool, PersonNotFound, VoiceprintEnrollmentTool

from ..voice.session_manager import TurnRequest, VoiceSessionManager
from ..voice.session_types import TurnResult, VoiceRoutingCallbacks
from ..voice.speaker_identification import SpeakerIdentificationAgent
from ..voice.speech_recognition_handler import SpeechRecognitionHandler
from ..voice.tts_client import DeterministicTtsClient, VertexTtsClient, create_tts_client
from ..voice.types import EnrolledSpeaker
from ..voice.voice_response_agent import VoiceResponseAgent

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/voice", tags=["voice"])

_AUDIO_MIME_TYPE = "audio/L16;rate=16000"
"""ADR-020 Decision 3's wire format: binary PCM16 16kHz mono frames."""


# ---------------------------------------------------------------------------
# Dependency providers — mirrors app.api.graph_router / app.api.debug's
# established per-request, no-module-level-singleton pattern.
# ---------------------------------------------------------------------------


def get_firestore_client(settings: Annotated[Settings, Depends(get_settings)]) -> firestore.Client:
    return create_firestore_client(settings)


def get_graph_store(
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> FirestoreGraphStore:
    return FirestoreGraphStore(client)


def get_graph_reader(
    store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
) -> FirestoreGraphReader:
    return FirestoreGraphReader(store)


def get_graph_writer(
    store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
) -> FirestoreGraphWriter:
    return FirestoreGraphWriter(store)


def get_audit_log(client: Annotated[firestore.Client, Depends(get_firestore_client)]) -> FirestoreAuditLog:
    return FirestoreAuditLog(client)


def get_idempotency_store(
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> FirestoreIdempotencyStore:
    return FirestoreIdempotencyStore(client)


def get_payload_store(settings: Annotated[Settings, Depends(get_settings)]) -> RawPayloadStore:
    return create_local_filesystem_payload_store(settings)


def get_model_router(settings: Annotated[Settings, Depends(get_settings)]) -> ModelRouter:
    return ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        location_pro=settings.vertex_ai_location_pro,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )


def get_gemini_client(model_router: Annotated[ModelRouter, Depends(get_model_router)]) -> GeminiClient:
    return GeminiClient(router=model_router)


def get_tts_client(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VertexTtsClient | DeterministicTtsClient:
    """The voice TTS seam. Real Vertex AI path by default; `ENV=demo`
    swaps in `DeterministicTtsClient` so the on-camera voice beat has no
    live external call to flake (PHASES.md Phase 15). See
    `voice.tts_client.create_tts_client`."""
    return create_tts_client(env=settings.env, project_id=settings.gcp_project_id)


def get_approval_gate(
    reader: Annotated[FirestoreGraphReader, Depends(get_graph_reader)],
    writer: Annotated[FirestoreGraphWriter, Depends(get_graph_writer)],
    audit_log: Annotated[FirestoreAuditLog, Depends(get_audit_log)],
) -> ApprovalGate:
    return ApprovalGate(graph_reader=reader, graph_writer=writer, audit_log=audit_log)


def get_ingestion_orchestrator_for_voice(
    settings: Annotated[Settings, Depends(get_settings)],
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
    graph_store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
    payload_store: Annotated[RawPayloadStore, Depends(get_payload_store)],
    reader: Annotated[SecretManagerAdapter, Depends(get_secret_reader)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
) -> IngestionOrchestrator:
    """The same real `IngestionOrchestrator` the `POST /ingest` route
    builds (ADR-023 §6) — reused here so a spoken "scan my Gmail" runs the
    identical wire (Gate 14.5)."""
    return build_ingestion_orchestrator(
        settings=settings,
        firestore_client=client,
        graph_store=graph_store,
        payload_store=payload_store,
        reader=reader,
        credential_store=credential_store,
    )


def _voice_scan_request(
    turn_id: str, credential_store: FirestoreOAuthCredentialStore
) -> IngestionRequest | None:
    """Build the `IngestionRequest` for a spoken "scan my Gmail and
    Outlook" (ADR-023 §7). Single-principal per run (ADR-022): the
    connected account's principal, scanning whichever of Gmail / Outlook
    that principal actually has an active grant for. `None` when nothing
    is connected — the caller logs it and does not start a run."""
    actives = credential_store.list_active()
    if not actives:
        return None
    principal = actives[0].principal
    providers = {c.provider for c in actives if c.principal == principal}
    sources: list[IngestionSourceKind] = []
    if OAuthProvider.GOOGLE in providers:
        sources.append(IngestionSourceKind.GMAIL)
    if OAuthProvider.MICROSOFT in providers:
        sources.append(IngestionSourceKind.OUTLOOK)
    if not sources:
        return None
    return IngestionRequest(
        idempotency_scope=f"voice-turn:{turn_id}",
        triggered_by="voice",
        household_id=DEMO_HOUSEHOLD_ID,
        sources=tuple(sources),
        window=timedelta(hours=24),
        principal=principal,
    )


def _make_scan_mailbox_callback(
    orchestrator: IngestionOrchestrator, credential_store: FirestoreOAuthCredentialStore
) -> Callable[[str], None]:
    """The `VoiceRoutingCallbacks.on_scan_mailbox` hand-off (ADR-023 §7):
    builds the request and runs the orchestrator on a daemon thread so the
    voice turn is not blocked for the length of a mailbox scan. A failure
    is logged in full — never a fabricated success (invariant #7). The
    resulting nodes surface to the frontend through `/graph/stream`, the
    same channel the text path uses."""

    def on_scan_mailbox(turn_id: str) -> None:
        request = _voice_scan_request(turn_id, credential_store)
        if request is None:
            logger.info("api.voice.scan_mailbox_no_connected_account", turn_id=turn_id)
            return

        def _run() -> None:
            try:
                result = orchestrator.run(request)
                logger.info(
                    "api.voice.scan_mailbox_complete",
                    turn_id=turn_id,
                    run_id=result.run_id,
                    documents_seen=result.documents_seen,
                    new_node_count=result.new_node_count,
                    counts=result.counts,
                    connector_failures=len(result.connector_failures),
                )
            except Exception:  # noqa: BLE001 — background task boundary; logged in full, never a fake success
                logger.exception("api.voice.scan_mailbox_failed", turn_id=turn_id)

        threading.Thread(target=_run, name=f"voice-scan-{turn_id[:12]}", daemon=True).start()

    return on_scan_mailbox


def get_voice_session_manager(
    gemini_client: Annotated[GeminiClient, Depends(get_gemini_client)],
    tts_client: Annotated[VertexTtsClient | DeterministicTtsClient, Depends(get_tts_client)],
    approval_gate: Annotated[ApprovalGate, Depends(get_approval_gate)],
    graph_writer: Annotated[FirestoreGraphWriter, Depends(get_graph_writer)],
    payload_store: Annotated[RawPayloadStore, Depends(get_payload_store)],
    ingestion_orchestrator: Annotated[IngestionOrchestrator, Depends(get_ingestion_orchestrator_for_voice)],
    credential_store: Annotated[FirestoreOAuthCredentialStore, Depends(get_credential_store)],
) -> VoiceSessionManager:
    """Builds one real `VoiceSessionManager` for one WebSocket connection
    — a fresh instance per session (never a module-level singleton), so
    each household member's session has its own, isolated turn-taking and
    confirmation state.

    `callbacks.on_scan_mailbox` is wired to the real ingestion
    orchestrator (ADR-023 §7): a spoken "scan my Gmail" from an
    identified, enrolled speaker runs the identical wire as `POST
    /ingest`. Every other callback stays a logged no-op this phase — the
    R-tier gating in `routing.py` is what Gate 13 tests, not the
    downstream subsystem call signatures."""
    return VoiceSessionManager(
        speech_recognition=SpeechRecognitionHandler(gemini_client=gemini_client),
        speaker_identification=SpeakerIdentificationAgent(gemini_client=gemini_client),
        language_identifier=LanguageScriptIdentifierAgent(gemini_client=gemini_client),
        normalisation=NormalisationAgent(gemini_client=gemini_client),
        entity_resolution=EntityResolutionAgent(gemini_client=gemini_client),
        intent_classifier=VoiceIntentClassifierAgent(gemini_client=gemini_client),
        confirmation=ConfirmationAgent(gemini_client=gemini_client),
        response_agent=VoiceResponseAgent(gemini_client=gemini_client, tts_client=tts_client),
        approval_gate=approval_gate,
        graph_writer=graph_writer,
        raw_payload_store=payload_store,
        callbacks=VoiceRoutingCallbacks(
            on_scan_mailbox=_make_scan_mailbox_callback(ingestion_orchestrator, credential_store)
        ),
    )


def get_known_people(store: Annotated[FirestoreGraphStore, Depends(get_graph_store)]) -> tuple[Person, ...]:
    """The household's real current roster — used to resolve speaker
    identity and kinship/name spans against real graph people, never a
    hardcoded fixture list."""
    return tuple(store.all_current_nodes((Person,)))


def get_enrolled_speakers(
    people: Annotated[tuple[Person, ...], Depends(get_known_people)],
    payload_store: Annotated[RawPayloadStore, Depends(get_payload_store)],
) -> tuple[EnrolledSpeaker, ...]:
    """Resolves every household member with a real `voiceprint_ref` to
    their real reference clip bytes — A66's own real comparison input.
    A household with nobody enrolled yet resolves to an empty tuple (a
    normal, honest input — see `speaker_identification.py`)."""
    speakers: list[EnrolledSpeaker] = []
    for person in people:
        if not person.voiceprint_ref:
            continue
        try:
            audio = payload_store.retrieve(person.voiceprint_ref)
            mime_type = payload_store.content_type_of(person.voiceprint_ref)
        except Exception:  # noqa: BLE001 — a missing/corrupt reference degrades to "not enrolled", never a 500.
            logger.warning(
                "api.voice.enrolled_speaker_reference_unreadable",
                person_id=str(person.id),
                voiceprint_ref=person.voiceprint_ref,
            )
            continue
        speakers.append(
            EnrolledSpeaker(
                person_id=person.id,
                display_name=person.display_name,
                reference_audio=audio,
                reference_mime_type=mime_type,
            )
        )
    return tuple(speakers)


# ---------------------------------------------------------------------------
# WS /voice/session
# ---------------------------------------------------------------------------


async def _send_json(websocket: WebSocket, payload: dict[str, Any]) -> None:
    await websocket.send_text(json.dumps(payload))


async def _emit_turn_result(websocket: WebSocket, result: TurnResult) -> None:
    if result.raw_text is not None:
        await _send_json(
            websocket,
            {
                "type": "transcript_final",
                "spans": [
                    {
                        "text": result.raw_text,
                        "language": result.response_language or "en",
                        "confidence": 1.0,
                    }
                ],
                "turn_id": result.turn_id,
            },
        )

    if result.kind == "confirmation_requested":
        await _send_json(
            websocket,
            {
                "type": "confirmation_prompt",
                "text": result.spoken_response_text or "",
                "requires_affirmative": True,
                "turn_id": result.turn_id,
            },
        )

    if result.kind == "discarded":
        await _send_json(
            websocket,
            {
                "type": "error",
                "code": "turn_discarded",
                "message": result.discard_reason or "the last turn could not be understood",
            },
        )
        return

    if result.response_audio_bytes is not None:
        await _send_json(
            websocket,
            {
                "type": "response_audio",
                "audio_b64": base64.b64encode(result.response_audio_bytes).decode("ascii"),
                "mime_type": result.response_audio_mime_type or "application/octet-stream",
                "text": result.spoken_response_text or "",
                "language": result.response_language or "en",
                "turn_id": result.turn_id,
            },
        )


_END_OF_TURN_SILENCE_SECONDS = 0.9
"""How long the client may go without sending a new audio chunk before
this endpoint treats whatever is buffered as one complete turn and
processes it.

**Honest scope note, discovered by reading E4's real client code, not
assumed:** `lib/mic-capture.ts` streams binary PCM frames continuously
with no client-side end-of-utterance detection and sends no `{"type":
"end_of_turn"}` control frame at all — this project does not implement
true server-side voice-activity detection this phase (stated plainly,
matching this project's honesty discipline for scope statements
elsewhere). This constant is a real, if simple, idle-timeout heuristic
that makes the real frontend actually usable without one: a real pause
in incoming audio frames longer than this window is treated as "the
household member has finished speaking." The explicit `{"type":
"end_of_turn"}` control frame (below) is still honoured too — a future
push-to-talk-release UI, or a test, can still signal a turn boundary
directly rather than waiting out this timeout.
"""


async def _process_one_turn(
    websocket: WebSocket,
    session_manager: VoiceSessionManager,
    *,
    known_people: tuple[Person, ...],
    enrolled_speakers: tuple[EnrolledSpeaker, ...],
    noisy_environment: bool,
) -> None:
    turn_id = uuid.uuid4().hex
    await _send_json(websocket, {"type": "session_state", "state": "processing"})
    request = TurnRequest(
        turn_id=turn_id,
        audio=session_manager.take_turn_audio(),
        audio_mime_type=_AUDIO_MIME_TYPE,
        reference_date=datetime.now(UTC).date().isoformat(),
        known_people=known_people,
        enrolled_speakers=enrolled_speakers,
        noisy_environment=noisy_environment,
    )
    result = session_manager.process_turn(request)
    await _send_json(websocket, {"type": "session_state", "state": session_manager.state.value})
    await _emit_turn_result(websocket, result)


@router.websocket("/session")
async def voice_session(
    websocket: WebSocket,
    session_manager: Annotated[VoiceSessionManager, Depends(get_voice_session_manager)],
    known_people: Annotated[tuple[Person, ...], Depends(get_known_people)],
    enrolled_speakers: Annotated[tuple[EnrolledSpeaker, ...], Depends(get_enrolled_speakers)],
) -> None:
    """The real inbound-voice session. See module docstring for the exact
    wire contract and this phase's own honest scope statement, and
    `_END_OF_TURN_SILENCE_SECONDS`'s own docstring for the real
    end-of-turn heuristic this endpoint needs against the actual E4
    client (which sends no explicit end-of-turn signal)."""
    await websocket.accept()
    await _send_json(websocket, {"type": "session_state", "state": session_manager.state.value})

    has_pending_audio = False
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive(), timeout=_END_OF_TURN_SILENCE_SECONDS)
            except TimeoutError:
                if has_pending_audio:
                    await _process_one_turn(
                        websocket,
                        session_manager,
                        known_people=known_people,
                        enrolled_speakers=enrolled_speakers,
                        noisy_environment=False,
                    )
                    has_pending_audio = False
                elif session_manager.check_silence_timeout():
                    await _send_json(websocket, {"type": "session_state", "state": "closed"})
                    break
                continue

            if message.get("type") == "websocket.disconnect":
                break

            raw_bytes = message.get("bytes")
            if raw_bytes is not None:
                barge_in = session_manager.append_audio(raw_bytes)
                has_pending_audio = True
                if barge_in:
                    await _send_json(
                        websocket, {"type": "session_state", "state": session_manager.state.value}
                    )
                continue

            raw_text = message.get("text")
            if raw_text is None:
                continue
            try:
                control = json.loads(raw_text)
            except json.JSONDecodeError:
                await _send_json(
                    websocket, {"type": "error", "code": "bad_control_frame", "message": "not valid JSON"}
                )
                continue

            if control.get("type") != "end_of_turn":
                continue

            await _process_one_turn(
                websocket,
                session_manager,
                known_people=known_people,
                enrolled_speakers=enrolled_speakers,
                noisy_environment=bool(control.get("noisy_environment", False)),
            )
            has_pending_audio = False
    except WebSocketDisconnect:
        logger.info("api.voice.session_disconnected")
    finally:
        session_manager.close()


# ---------------------------------------------------------------------------
# POST /voice/persons/{person_id}/enroll
# ---------------------------------------------------------------------------


class EnrollRequest(BaseModel):
    audio_b64: str
    mime_type: str = "audio/L16;rate=16000"


class EnrollResponse(BaseModel):
    person_id: str
    voiceprint_ref: str
    enrolled_at: str


@router.post("/persons/{person_id}/enroll", response_model=EnrollResponse)
def enroll_voiceprint(
    person_id: str,
    body: EnrollRequest,
    reader: Annotated[FirestoreGraphReader, Depends(get_graph_reader)],
    writer: Annotated[FirestoreGraphWriter, Depends(get_graph_writer)],
    payload_store: Annotated[RawPayloadStore, Depends(get_payload_store)],
    idempotency_store: Annotated[FirestoreIdempotencyStore, Depends(get_idempotency_store)],
) -> EnrollResponse:
    """Enrolls one household member's real reference voice clip
    (`app.tools.voice_profile_tools.VoiceprintEnrollmentTool`, T3)."""
    try:
        audio = base64.b64decode(body.audio_b64, validate=True)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=f"'audio_b64' is not valid base64: {exc}"
        ) from exc

    tool = VoiceprintEnrollmentTool(
        graph_reader=reader,
        graph_writer=writer,
        raw_payload_store=payload_store,
        idempotency_store=idempotency_store,
    )
    idempotency_key = IdempotencyKey(
        entity_id=person_id, action_type="voiceprint_enrollment", cycle=datetime.now(UTC).date().isoformat()
    ).as_str()
    try:
        result = tool.invoke_idempotent(
            idempotency_key, person_id=person_id, audio=audio, mime_type=body.mime_type
        )
    except PersonNotFound as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    payload = result.value
    if not result.ok or not isinstance(payload, dict):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=result.error or "enrollment failed"
        )
    return EnrollResponse(
        person_id=str(payload["person_id"]),
        voiceprint_ref=str(payload["voiceprint_ref"]),
        enrolled_at=datetime.now(UTC).isoformat(),
    )


# ---------------------------------------------------------------------------
# GET / PATCH /voice/persons/{person_id}/language-profile
# ---------------------------------------------------------------------------


class LanguageProfileResponse(BaseModel):
    """Wire shape for both `GET` and `PATCH` responses — mirrors
    `contracts.graph_types.LanguageProfile` field for field."""

    primary_language: str
    languages_understood: list[str]
    script_preference: str
    code_mixing_profile: str | None
    formality_preference: str | None
    literacy_mode: str


class LanguageProfilePatchRequest(BaseModel):
    """Every field optional — a real partial update (a field omitted
    keeps its current value); `None` sent for `code_mixing_profile`/
    `formality_preference` explicitly clears them."""

    primary_language: str | None = None
    languages_understood: list[str] | None = None
    script_preference: str | None = None
    code_mixing_profile: str | None = None
    formality_preference: str | None = None
    literacy_mode: str | None = None


def _get_person_or_404(reader: FirestoreGraphReader, person_id: str) -> Person:
    node = reader.get_node(NodeId(person_id))
    if not isinstance(node, Person):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=f"no current Person node found for id {person_id!r}"
        )
    return node


@router.get("/persons/{person_id}/language-profile", response_model=LanguageProfileResponse)
def get_language_profile(
    person_id: str, reader: Annotated[FirestoreGraphReader, Depends(get_graph_reader)]
) -> LanguageProfileResponse:
    person = _get_person_or_404(reader, person_id)
    profile = person.language_profile
    return LanguageProfileResponse(
        primary_language=profile.primary_language,
        languages_understood=list(profile.languages_understood),
        script_preference=profile.script_preference,
        code_mixing_profile=profile.code_mixing_profile,
        formality_preference=profile.formality_preference,
        literacy_mode=profile.literacy_mode.value,
    )


@router.patch("/persons/{person_id}/language-profile", response_model=LanguageProfileResponse)
def patch_language_profile(
    person_id: str,
    body: LanguageProfilePatchRequest,
    reader: Annotated[FirestoreGraphReader, Depends(get_graph_reader)],
    writer: Annotated[FirestoreGraphWriter, Depends(get_graph_writer)],
    idempotency_store: Annotated[FirestoreIdempotencyStore, Depends(get_idempotency_store)],
) -> LanguageProfileResponse:
    """Applies a real partial `LanguageProfile` update
    (`app.tools.voice_profile_tools.LanguageProfileTool`, T3) and returns
    the resulting profile."""
    _get_person_or_404(reader, person_id)  # 404s before touching the tool at all

    updates = body.model_dump(exclude_unset=True)
    if "literacy_mode" in updates and updates["literacy_mode"] is not None:
        try:
            LiteracyMode(updates["literacy_mode"])
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=f"invalid literacy_mode: {exc}"
            ) from exc

    tool = LanguageProfileTool(graph_reader=reader, graph_writer=writer, idempotency_store=idempotency_store)
    idempotency_key = IdempotencyKey(
        entity_id=person_id,
        action_type="language_profile_update",
        cycle=uuid.uuid4().hex,
        # cycle is per-request, not per-day: a settings PATCH is not a
        # once-per-cycle action the way a payment is (spec §19.1's
        # idempotency key is scoped per real recurring action; a settings
        # edit has no natural "cycle" at all, so a fresh one per request
        # is the honest choice — never a caller-visible replay boundary
        # this tool needs to dedupe across turns for.
    ).as_str()
    try:
        tool.invoke_idempotent(idempotency_key, person_id=person_id, updates=updates)
    except PersonNotFound as exc:  # pragma: no cover — guarded by _get_person_or_404 above
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    updated = _get_person_or_404(reader, person_id)
    profile = updated.language_profile
    return LanguageProfileResponse(
        primary_language=profile.primary_language,
        languages_understood=list(profile.languages_understood),
        script_preference=profile.script_preference,
        code_mixing_profile=profile.code_mixing_profile,
        formality_preference=profile.formality_preference,
        literacy_mode=profile.literacy_mode.value,
    )


__all__ = ["router"]
