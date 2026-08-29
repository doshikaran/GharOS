"""HTTP/WebSocket-level tests for `app.api.voice_router` (PHASES.md
Phase 13, ADR-020 Decision 3).

Enrollment/language-profile endpoints run against a real Firestore
emulator (`writer`/`reader`/`store` fixtures) — the same real,
provenance-guarded write path `test_graph_router.py` already established
for this codebase's HTTP-layer integration tests. The WebSocket session
endpoint is tested with `get_voice_session_manager` overridden to a
lightweight fake (`_FakeSessionManager`) satisfying only the methods the
router itself calls — this proves the real wire contract (ADR-020
Decision 3's exact frame shapes) independent of any LLM call, which is
already covered end-to-end by `test_voice_session_manager.py`'s own full
real-pipeline tests.
"""

from __future__ import annotations

import base64
import json
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
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
from fastapi.testclient import TestClient

from app.api.voice_router import (
    get_enrolled_speakers,
    get_graph_reader,
    get_graph_store,
    get_graph_writer,
    get_idempotency_store,
    get_known_people,
    get_payload_store,
    get_voice_session_manager,
)
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.main import app
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.voice.session_types import TurnResult
from app.voice.types import SessionState

from ._fake_raw_payload_store import FakeRawPayloadStore


def _person(person_id: str = "person-1") -> Person:
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


@pytest.fixture
def client(
    store: FirestoreGraphStore,
    reader: FirestoreGraphReader,
    writer: FirestoreGraphWriter,
    idempotency_store: FirestoreIdempotencyStore,
) -> Iterator[TestClient]:
    app.dependency_overrides[get_graph_store] = lambda: store
    app.dependency_overrides[get_graph_reader] = lambda: reader
    app.dependency_overrides[get_graph_writer] = lambda: writer
    app.dependency_overrides[get_idempotency_store] = lambda: idempotency_store
    app.dependency_overrides[get_payload_store] = FakeRawPayloadStore
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


class TestEnrollVoiceprint:
    def test_enrolls_a_seeded_person(
        self, client: TestClient, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        writer.write_node(_person())
        body = {"audio_b64": base64.b64encode(b"\x00\x01\x02").decode("ascii"), "mime_type": "audio/L16"}

        response = client.post("/voice/persons/person-1/enroll", json=body)

        assert response.status_code == 200
        payload = response.json()
        assert payload["person_id"] == "person-1"
        assert payload["voiceprint_ref"]
        updated = reader.get_node(NodeId("person-1"))
        assert isinstance(updated, Person)
        assert updated.voiceprint_ref == payload["voiceprint_ref"]

    def test_404_for_unknown_person(self, client: TestClient) -> None:
        body = {"audio_b64": base64.b64encode(b"\x00\x01").decode("ascii")}
        response = client.post("/voice/persons/does-not-exist/enroll", json=body)
        assert response.status_code == 404

    def test_400_for_invalid_base64(self, client: TestClient) -> None:
        response = client.post("/voice/persons/person-1/enroll", json={"audio_b64": "not valid base64!!!"})
        assert response.status_code == 400


class TestLanguageProfileEndpoints:
    def test_get_returns_the_current_profile(self, client: TestClient, writer: FirestoreGraphWriter) -> None:
        writer.write_node(_person())
        response = client.get("/voice/persons/person-1/language-profile")
        assert response.status_code == 200
        body = response.json()
        assert body["primary_language"] == "hi"
        assert body["languages_understood"] == ["hi", "en"]
        assert body["literacy_mode"] == "both"

    def test_get_404_for_unknown_person(self, client: TestClient) -> None:
        response = client.get("/voice/persons/does-not-exist/language-profile")
        assert response.status_code == 404

    def test_patch_applies_a_real_partial_update(
        self, client: TestClient, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        writer.write_node(_person())

        response = client.patch("/voice/persons/person-1/language-profile", json={"primary_language": "en"})

        assert response.status_code == 200
        body = response.json()
        assert body["primary_language"] == "en"
        assert body["script_preference"] == "devanagari"  # unchanged
        updated = reader.get_node(NodeId("person-1"))
        assert isinstance(updated, Person)
        assert updated.language_profile.primary_language == "en"

    def test_patch_invalid_literacy_mode_is_400(
        self, client: TestClient, writer: FirestoreGraphWriter
    ) -> None:
        writer.write_node(_person())
        response = client.patch(
            "/voice/persons/person-1/language-profile", json={"literacy_mode": "not-a-real-mode"}
        )
        assert response.status_code == 400

    def test_patch_404_for_unknown_person(self, client: TestClient) -> None:
        response = client.patch(
            "/voice/persons/does-not-exist/language-profile", json={"primary_language": "en"}
        )
        assert response.status_code == 404


class _FakeSessionManager:
    """Satisfies only the methods `app.api.voice_router.voice_session`
    actually calls on a `VoiceSessionManager` — a deliberate, lightweight
    stand-in (see module docstring) proving the real wire contract
    independent of any LLM call."""

    def __init__(self, *, silence_timed_out: bool = False) -> None:
        self.state = SessionState.LISTENING
        self.appended: list[bytes] = []
        self.closed = False
        self.silence_timed_out = silence_timed_out
        self.turn_results: list[TurnResult] = [
            TurnResult(
                turn_id="fake-turn-1",
                kind="completed",
                raw_text="turn on the lights",
                spoken_response_text="Turning on the lights now.",
                response_audio_bytes=b"\x01\x02\x03",
                response_audio_mime_type="audio/L16;codec=pcm;rate=24000",
                response_language="en",
                confirmation=None,
                routing_outcome=None,
            )
        ]

    def append_audio(self, chunk: bytes) -> bool:
        self.appended.append(chunk)
        barge_in = self.state is SessionState.SPEAKING
        self.state = SessionState.LISTENING
        return barge_in

    def take_turn_audio(self) -> bytes:
        audio = b"".join(self.appended)
        self.appended = []
        return audio

    def process_turn(self, request: object) -> TurnResult:
        self.state = SessionState.SPEAKING
        return self.turn_results.pop(0)

    def check_silence_timeout(self) -> bool:
        return self.silence_timed_out

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def ws_client(store: FirestoreGraphStore) -> Iterator[tuple[TestClient, _FakeSessionManager]]:
    fake_manager = _FakeSessionManager()
    app.dependency_overrides[get_voice_session_manager] = lambda: fake_manager
    app.dependency_overrides[get_known_people] = lambda: ()
    app.dependency_overrides[get_enrolled_speakers] = lambda: ()
    app.dependency_overrides[get_graph_store] = lambda: store
    try:
        yield TestClient(app), fake_manager
    finally:
        app.dependency_overrides.clear()


class TestVoiceSessionWebSocket:
    def test_full_turn_round_trip_emits_the_exact_wire_contract_frames(
        self, ws_client: tuple[TestClient, _FakeSessionManager]
    ) -> None:
        client, fake_manager = ws_client
        with client.websocket_connect("/voice/session") as websocket:
            initial = json.loads(websocket.receive_text())
            assert initial == {"type": "session_state", "state": "listening"}

            websocket.send_bytes(b"\x00\x01" * 10)
            websocket.send_text(json.dumps({"type": "end_of_turn"}))

            processing = json.loads(websocket.receive_text())
            assert processing == {"type": "session_state", "state": "processing"}

            after_turn_state = json.loads(websocket.receive_text())
            assert after_turn_state == {"type": "session_state", "state": "speaking"}

            transcript = json.loads(websocket.receive_text())
            assert transcript["type"] == "transcript_final"
            assert transcript["spans"][0]["text"] == "turn on the lights"

            response_audio = json.loads(websocket.receive_text())
            assert response_audio["type"] == "response_audio"
            assert response_audio["mime_type"] == "audio/L16;codec=pcm;rate=24000"
            assert base64.b64decode(response_audio["audio_b64"]) == b"\x01\x02\x03"
            assert response_audio["text"] == "Turning on the lights now."

        assert fake_manager.closed is True
        assert fake_manager.appended == []  # consumed by take_turn_audio

    def test_barge_in_emits_a_session_state_frame(
        self, ws_client: tuple[TestClient, _FakeSessionManager]
    ) -> None:
        client, fake_manager = ws_client
        fake_manager.state = SessionState.SPEAKING
        with client.websocket_connect("/voice/session") as websocket:
            websocket.receive_text()  # initial session_state
            websocket.send_bytes(b"\x02\x03")
            barge_in_frame = json.loads(websocket.receive_text())
            assert barge_in_frame == {"type": "session_state", "state": "listening"}

    def test_silence_after_audio_auto_ends_the_turn_with_no_control_frame(
        self, ws_client: tuple[TestClient, _FakeSessionManager]
    ) -> None:
        """The real integration fix this phase made after reading E4's
        actual `lib/mic-capture.ts`: it streams binary frames continuously
        and never sends a `{"type": "end_of_turn"}` control frame at all.
        A real pause in incoming audio (`_END_OF_TURN_SILENCE_SECONDS`)
        must, on its own, trigger the same turn-processing path."""
        client, fake_manager = ws_client
        with client.websocket_connect("/voice/session") as websocket:
            websocket.receive_text()  # initial session_state

            websocket.send_bytes(b"\x00\x01" * 10)
            # No end_of_turn control frame sent at all — silence alone
            # must trigger processing within _END_OF_TURN_SILENCE_SECONDS.

            processing = json.loads(websocket.receive_text())
            assert processing == {"type": "session_state", "state": "processing"}
            after_turn_state = json.loads(websocket.receive_text())
            assert after_turn_state == {"type": "session_state", "state": "speaking"}
            transcript = json.loads(websocket.receive_text())
            assert transcript["type"] == "transcript_final"

        assert fake_manager.appended == []

    def test_full_session_silence_closes_the_session(
        self, ws_client: tuple[TestClient, _FakeSessionManager]
    ) -> None:
        """No audio at all, ever — `VoiceSessionManager.check_silence_
        timeout` eventually reports the session should close, and this
        endpoint sends a real `session_state: closed` frame rather than
        holding the WebSocket open forever."""
        client, fake_manager = ws_client
        fake_manager.silence_timed_out = True
        with client.websocket_connect("/voice/session") as websocket:
            websocket.receive_text()  # initial session_state
            closed_frame = json.loads(websocket.receive_text())
            assert closed_frame == {"type": "session_state", "state": "closed"}
        assert fake_manager.closed is True


__all__: list[str] = []
