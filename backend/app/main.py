"""GharOS backend — FastAPI application entrypoint.

Phase 0: a minimal app exposing `/health` only, matching the Procfile's
`app.main:app` target (`backend/Procfile`, owned by E3). Phase 2 adds two
routers — the Pub/Sub push receiver (`app.api.pubsub_receiver`, E3 —
PHASES.md Phase 2 work items 2/5) and the mandatory-stack-proof diagnostic
endpoints (`app.api.debug`, E2 — PHASES.md Gate 2 requirements 1/2) — and
CORS support, since `gharos-web` (E4's `/status` page) fetches these
endpoints cross-origin from a separately-deployed Cloud Run service.

Phase 6 adds the graph-visualisation router (`app.api.graph_router`, E1 —
PHASES.md Phase 6 work item: "streaming/subscription endpoint for live
mutations; path query API") and, with it, this module's first `lifespan`
context manager: `GET /graph/stream` needs exactly one shared
`FirestoreGraphChangeStream` broadcaster constructed once at app startup
(never per HTTP connection — see that module's docstring), so the
lifespan builds one `firestore.Client` + one change-stream instance,
starts its Firestore listeners, and stores both on `app.state` for
`app.api.graph_router`'s dependency providers to read.

This module stays thin; it wires, it does not implement.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.debug import router as debug_router
from app.api.graph_router import router as graph_router
from app.api.pubsub_receiver import router as pubsub_router
from app.graph.change_stream import FirestoreGraphChangeStream
from app.persistence.firestore_client import create_firestore_client
from app.settings import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Constructs the one shared `firestore.Client` + `FirestoreGraph
    ChangeStream` this process uses for `GET /graph/stream`, opens its 17
    Firestore listeners, and releases them cleanly on shutdown."""
    settings = get_settings()
    client = create_firestore_client(settings)
    change_stream = FirestoreGraphChangeStream(client)
    change_stream.start()
    app.state.firestore_client = client
    app.state.graph_change_stream = change_stream
    try:
        yield
    finally:
        change_stream.stop()
        client.close()  # type: ignore[no-untyped-call]


app = FastAPI(title="GharOS backend", lifespan=lifespan)

_settings = get_settings()
_allowed_origins = _settings.cors_allowed_origins_list
if _allowed_origins:
    # Exact-origin allowlist only — never a wildcard (see
    # Settings.cors_allowed_origins's docstring). GET-only today (every
    # Phase 2 endpoint is a read/debug check); revisit `allow_methods` when
    # a real T3+ write endpoint is ever meant to be called directly from
    # the browser, which is not the plan (writes go through the Approval
    # Gate, not a client-side fetch).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_origins,
        allow_methods=["GET"],
        allow_headers=["*"],
    )

app.include_router(pubsub_router)
app.include_router(debug_router)
app.include_router(graph_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns process status only — no I/O, no auth."""
    return {"status": "ok"}


@app.get("/health/config")
def health_config() -> dict[str, str]:
    """Diagnostic endpoint confirming settings load correctly, without ever
    echoing secret values (there are none in this settings model, but the
    pattern is to report presence/shape, not raw values)."""
    settings = get_settings()
    return {"env": settings.env, "gcp_region": settings.gcp_region}
