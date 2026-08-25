"""HTTP-level proof that `GET /graph/stream` genuinely streams live
mutations through the real FastAPI route (real SSE framing, real
`Content-Type`), not just that `FirestoreGraphChangeStream` works in
isolation (`test_graph_change_stream.py` covers that at the class level).

**Why a real `uvicorn` server, not `TestClient`/`httpx.ASGITransport`:**
tried first, and it deadlocks. Starlette's `StreamingResponse` runs a
concurrent "listen for client disconnect" task alongside the body
generator; `httpx.ASGITransport`'s in-process `receive()` never resolves
that disconnect-listen task until the response is already complete
(confirmed directly — see this phase's report), which is fine for a
response that finishes on its own but deadlocks against a genuinely
open-ended stream like this one. A real `uvicorn` server on a real
loopback TCP socket, read with a real (sync) `httpx.Client`, has no such
limitation and is what this test uses — the same shape a real browser's
`EventSource` connection has.

This test's server and its `FirestoreGraphChangeStream` both bind to one
throwaway Firestore-emulator project id (`GCP_PROJECT_ID` env var,
process-wide for the duration of this test only, restored after) so the
live server and this test's own `writer` fixture-equivalent write to the
exact same graph the server is watching.
"""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import uvicorn
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    PersonRole,
    Provenance,
)
from google.cloud import firestore

from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from app.settings import get_settings

_SERVER_START_TIMEOUT_SECONDS = 15.0
_STREAM_READ_TIMEOUT_SECONDS = 20.0


def _make_person(node_id: str, display_name: str) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=0.9,
            deriving_agent=AgentId("A0"),
            created_at=datetime(2026, 8, 22, tzinfo=UTC),
        ),
        display_name=display_name,
        aliases=(),
        role=PersonRole.ADULT,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=LanguageProfile(
            primary_language="en",
            languages_understood=("en",),
            script_preference="latin",
            code_mixing_profile=None,
            formality_preference=None,
            literacy_mode=LiteracyMode.BOTH,
        ),
    )


@pytest.fixture
def live_server_project_id() -> Iterator[str]:
    """Points `GCP_PROJECT_ID` (and, via `get_settings.cache_clear()`, the
    process-wide cached `Settings`) at one throwaway emulator project id
    for the duration of this test only, then restores the prior state —
    this is what lets `app.main`'s real `lifespan` (constructed against
    `get_settings()`) and this test's own writer agree on which graph
    they're both touching."""
    project_id = f"gharos-test-{uuid.uuid4().hex[:16]}"
    previous = os.environ.get("GCP_PROJECT_ID")
    os.environ["GCP_PROJECT_ID"] = project_id
    get_settings.cache_clear()
    try:
        yield project_id
    finally:
        if previous is None:
            os.environ.pop("GCP_PROJECT_ID", None)
        else:
            os.environ["GCP_PROJECT_ID"] = previous
        get_settings.cache_clear()


@pytest.fixture
def live_server(live_server_project_id: str) -> Iterator[str]:
    """Runs the real `app.main.app` (real `lifespan`, real
    `FirestoreGraphChangeStream`) on a real loopback TCP port in a
    background thread. Yields the server's base URL."""
    # app.main's `lifespan` calls `get_settings()` fresh every time it
    # runs (at real ASGI startup, triggered below by `server.run()` in the
    # background thread) — never at import time — so it always picks up
    # whatever `GCP_PROJECT_ID` `live_server_project_id` set, regardless
    # of whether `app.main` was already imported by an earlier test.
    from app.main import app as fastapi_app

    # port=0: the OS assigns a genuinely free port atomically at uvicorn's
    # own bind call, inside server.startup() -- no separate "probe a free
    # port, close the probe socket, then rebind" step (the previous
    # `_free_port()` helper's approach) exists to race against. That
    # bind-close-then-rebind pattern has an inherent, if small, window
    # where another process/thread claims the same port in the gap; under
    # the full test suite's real resource pressure (many concurrent
    # sockets/threads across Firestore-emulator connections and other
    # tests) this raced exactly once during Phase 6's own gate review,
    # surfacing as an uncaught `SystemExit` from uvicorn's background
    # thread (pytest correctly reports an unhandled-thread-exception error
    # for that, rather than either retrying or failing this test cleanly).
    # Reading the real assigned port back from the server's own listening
    # socket after startup removes the race rather than papering over it.
    config = uvicorn.Config(fastapi_app, host="127.0.0.1", port=0, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + _SERVER_START_TIMEOUT_SECONDS
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("live uvicorn test server did not start in time")
        time.sleep(0.05)

    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def test_stream_endpoint_delivers_a_live_write_as_real_sse(
    live_server: str, live_server_project_id: str
) -> None:
    client = firestore.Client(project=live_server_project_id, database="(default)")
    try:
        writer = FirestoreGraphWriter(FirestoreGraphStore(client))

        def write_after_a_beat() -> None:
            time.sleep(0.5)
            writer.write_node(_make_person("person-sse-live", "Streamed live"))

        writer_thread = threading.Thread(target=write_after_a_beat, daemon=True)
        writer_thread.start()

        found_event = False
        found_data = False
        with httpx.Client(timeout=_STREAM_READ_TIMEOUT_SECONDS) as http_client:
            with http_client.stream("GET", f"{live_server}/graph/stream") as response:
                assert response.status_code == 200
                assert response.headers["content-type"].startswith("text/event-stream")

                deadline = time.monotonic() + _STREAM_READ_TIMEOUT_SECONDS
                for line in response.iter_lines():
                    if line.startswith("event: node"):
                        found_event = True
                        continue
                    if found_event and line.startswith("data: "):
                        assert '"id": "person-sse-live"' in line
                        assert '"type": "PERSON"' in line
                        assert '"label": "Streamed live"' in line
                        found_data = True
                        break
                    if time.monotonic() > deadline:
                        break

        writer_thread.join(timeout=5)
        assert found_event, "no 'event: node' line was ever received"
        assert found_data, "no matching 'data:' line was ever received"
    finally:
        client.close()  # type: ignore[no-untyped-call]
