"""GharOS — the graph-visualisation-facing HTTP surface (PHASES.md Phase 6,
E1 work item: "streaming/subscription endpoint for live mutations; path
query API"). Follows the same thin-router convention `app.api.debug`
(E2, Phase 2) and `app.api.pubsub_receiver` (E3, Phase 2) already
established: `backend/app/api/` is not owned by one role, each router
module is owned by whichever phase's work needed it, and `app.main` wires
every router in with `app.include_router(...)`.

Four endpoints, all frozen by the CTO for this phase (both this router and
E4's frontend graph view, dispatched after E1 against this real working
API, build against the exact same shapes):

- `GET /graph/snapshot` — every current node/edge in the store, once.
- `GET /graph/stream` — Server-Sent Events, live mutations only, no replay
  of existing state (`/graph/snapshot` is what covers that).
- `GET /graph/nodes/{node_id}/justification` — the walkable justification
  chain from a conclusion node back to its evidentiary SOURCE_DOCUMENT
  roots (`app.graph.justification.JustificationExplainer`).
- `GET /documents/{document_id}/raw` — a SOURCE_DOCUMENT's raw payload
  bytes, with the real content type as the response's `Content-Type`.

**Node/edge wire shape and the node-type tag convention are defined once,
in `app.graph.serialization`** (its module docstring is the canonical
spec for `"type"`, `"label"`, and every other field below) — this module
only wires HTTP concerns (routing, dependency injection, status codes)
around that shared shape; it never redefines it.

**Dependency injection, matching `app.api.debug`'s established pattern:**
`get_firestore_client` / `get_graph_store` build a fresh, cheap
(no eager I/O at construction) `FirestoreGraphStore` per request via
`Depends` — never a module-level singleton. `GET /graph/stream` is the one
exception: its `FirestoreGraphChangeStream` broadcaster is deliberately
*not* built per request (PHASES.md Phase 6's own explicit requirement —
17 shared Firestore listeners, not 17 per connecting browser tab), so
`get_graph_change_stream` instead reads the single instance `app.main`'s
lifespan constructed once at startup and stored on `request.app.state`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any

import structlog
from contracts.graph_types import NodeId, SourceDocument
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import StreamingResponse
from google.cloud import firestore
from pydantic import BaseModel

from app.graph.change_stream import FirestoreGraphChangeStream, GraphChangeEvent
from app.graph.errors import NodeNotFound
from app.graph.justification import JustificationExplainer
from app.graph.serialization import build_edge_envelope, build_node_envelope
from app.persistence.errors import RawPayloadNotFound
from app.persistence.firestore_client import create_firestore_client
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.raw_payload_store import RawPayloadStore, create_local_filesystem_payload_store
from app.settings import Settings, get_settings

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["graph"])

_SSE_MEDIA_TYPE = "text/event-stream"


# ---------------------------------------------------------------------------
# Dependency providers
# ---------------------------------------------------------------------------


def get_firestore_client(settings: Annotated[Settings, Depends(get_settings)]) -> firestore.Client:
    """A fresh `firestore.Client` per request — construction performs no
    eager network I/O, so this stays cheap; mirrors `app.api.debug`'s
    `get_model_router` pattern (dependency-injected, never a module-level
    singleton holding I/O)."""
    return create_firestore_client(settings)


def get_graph_store(
    client: Annotated[firestore.Client, Depends(get_firestore_client)],
) -> FirestoreGraphStore:
    return FirestoreGraphStore(client)


def get_justification_explainer(
    store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
) -> JustificationExplainer:
    return JustificationExplainer(store)


def get_payload_store(settings: Annotated[Settings, Depends(get_settings)]) -> RawPayloadStore:
    return create_local_filesystem_payload_store(settings)


def get_graph_change_stream(request: Request) -> FirestoreGraphChangeStream:
    """Returns the single `FirestoreGraphChangeStream` `app.main`'s
    lifespan constructed at startup — deliberately *not* built here per
    request (see this module's docstring)."""
    change_stream = getattr(request.app.state, "graph_change_stream", None)
    if change_stream is None:
        # Structurally shouldn't happen once app.main's lifespan is wired,
        # but a clear 503 beats an AttributeError reaching the client if a
        # future composition change ever drops the wiring.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="graph change stream is not initialised",
        )
    return change_stream  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# Response models — mirror app.graph.serialization's wire shape exactly
# ---------------------------------------------------------------------------


class NodeEnvelope(BaseModel):
    id: str
    type: str
    label: str
    derivation: str | None
    confidence: float | None
    source_document_id: str | None
    region: str | None
    created_at: str | None
    fields: dict[str, Any]


class EdgeEnvelope(BaseModel):
    id: str
    type: str
    from_id: str
    to_id: str
    derivation: str | None
    confidence: float | None
    is_conflict: bool


class GraphSnapshotResponse(BaseModel):
    nodes: list[NodeEnvelope]
    edges: list[EdgeEnvelope]


class EdgeSummary(BaseModel):
    id: str
    type: str
    from_id: str
    to_id: str


class JustificationStepModel(BaseModel):
    node_id: str
    depth: int
    via_edge: EdgeSummary | None


class JustificationSourceDocumentModel(BaseModel):
    id: str
    channel: str
    region: str | None


class JustificationResponse(BaseModel):
    root_node_id: str
    steps: list[JustificationStepModel]
    source_documents: list[JustificationSourceDocumentModel]


# ---------------------------------------------------------------------------
# 1. GET /graph/snapshot
# ---------------------------------------------------------------------------


@router.get("/graph/snapshot", response_model=GraphSnapshotResponse)
def get_graph_snapshot(
    store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
) -> GraphSnapshotResponse:
    """Every current (non-superseded) node and edge in the store, once.

    Built directly from raw, undecoded Firestore documents
    (`FirestoreGraphStore.all_current_node_documents` /
    `all_edge_documents`) — see `app.graph.serialization`'s module
    docstring for why this deliberately skips the typed decoders.
    """
    nodes = [
        NodeEnvelope(**build_node_envelope(node_type, doc_id, raw))
        for node_type, doc_id, raw in store.all_current_node_documents()
        if raw is not None
    ]
    edges = [
        EdgeEnvelope(**build_edge_envelope(doc_id, raw))
        for doc_id, raw in store.all_edge_documents()
        if raw is not None
    ]
    return GraphSnapshotResponse(nodes=nodes, edges=edges)


# ---------------------------------------------------------------------------
# 2. GET /graph/stream
# ---------------------------------------------------------------------------


def _format_sse_event(event: GraphChangeEvent) -> str:
    return f"event: {event.kind}\ndata: {json.dumps(event.payload)}\n\n"


_SSE_HEARTBEAT_COMMENT = ": heartbeat\n\n"
"""An SSE comment line (leading `:`) — ignored by every conforming SSE
client, sent purely so Cloud Run / any intermediate proxy never times out
an otherwise-idle connection."""


async def _sse_event_source(
    request: Request,
    change_stream: FirestoreGraphChangeStream,
    heartbeat_interval_seconds: float,
) -> AsyncIterator[str]:
    queue = change_stream.subscribe()
    try:
        while True:
            if await request.is_disconnected():
                break
            try:
                event = await asyncio.wait_for(queue.get(), timeout=heartbeat_interval_seconds)
            except TimeoutError:
                yield _SSE_HEARTBEAT_COMMENT
                continue
            yield _format_sse_event(event)
    finally:
        change_stream.unsubscribe(queue)


@router.get("/graph/stream")
async def stream_graph(
    request: Request,
    change_stream: Annotated[FirestoreGraphChangeStream, Depends(get_graph_change_stream)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> StreamingResponse:
    """Server-Sent Events: every node/edge write that happens *after* this
    client connects — never a replay of existing state (spec: use
    `GET /graph/snapshot` for that). Event format:

        event: node
        data: {"id": "...", "type": "...", ...same shape as a
               /graph/snapshot node...}

        event: edge
        data: {"id": "...", ...same shape as a /graph/snapshot edge...}
    """
    return StreamingResponse(
        _sse_event_source(request, change_stream, settings.sse_heartbeat_interval_seconds),
        media_type=_SSE_MEDIA_TYPE,
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ---------------------------------------------------------------------------
# 3. GET /graph/nodes/{node_id}/justification
# ---------------------------------------------------------------------------


@router.get("/graph/nodes/{node_id}/justification", response_model=JustificationResponse)
def get_node_justification(
    node_id: str,
    explainer: Annotated[JustificationExplainer, Depends(get_justification_explainer)],
) -> JustificationResponse:
    """The walkable justification chain from `node_id` (a "conclusion" —
    typically an OBLIGATION, DECISION, or CONFLICTS_WITH-involved node)
    back to its evidentiary SOURCE_DOCUMENT roots.

    Raises:
        HTTPException: 404 if `node_id` does not resolve to any current
            node — a malformed/unresolvable id is a caller error, never a
            500.
    """
    try:
        result = explainer.explain(NodeId(node_id))
    except NodeNotFound as exc:
        logger.info("api.graph.justification.node_not_found", node_id=node_id)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return JustificationResponse(
        root_node_id=result.root_node_id,
        steps=[
            JustificationStepModel(
                node_id=step.node_id,
                depth=step.depth,
                via_edge=EdgeSummary(**step.via_edge) if step.via_edge is not None else None,
            )
            for step in result.steps
        ],
        source_documents=[
            JustificationSourceDocumentModel(id=doc.id, channel=doc.channel, region=doc.region)
            for doc in result.source_documents
        ],
    )


# ---------------------------------------------------------------------------
# 4. GET /documents/{document_id}/raw
# ---------------------------------------------------------------------------


@router.get("/documents/{document_id}/raw")
def get_document_raw(
    document_id: str,
    store: Annotated[FirestoreGraphStore, Depends(get_graph_store)],
    payload_store: Annotated[RawPayloadStore, Depends(get_payload_store)],
) -> Response:
    """Resolves `document_id` to its `SourceDocument` node, then returns
    its raw payload bytes with the real stored content type as
    `Content-Type` — what lets a node inspector render a text body as text
    or an image blob as an image directly.

    Raises:
        HTTPException: 404 if `document_id` does not resolve to a current
            `SourceDocument` node, or its `raw_payload_ref` does not
            resolve to any stored payload.
    """
    node = store.get_node(NodeId(document_id))
    if not isinstance(node, SourceDocument):
        logger.info("api.graph.document_raw.not_found", document_id=document_id)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"no SOURCE_DOCUMENT node found for id {document_id!r}",
        )
    try:
        payload = payload_store.retrieve(node.raw_payload_ref)
        content_type = payload_store.content_type_of(node.raw_payload_ref)
    except RawPayloadNotFound as exc:
        logger.warning(
            "api.graph.document_raw.payload_missing",
            document_id=document_id,
            raw_payload_ref=node.raw_payload_ref,
        )
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    return Response(content=payload, media_type=content_type)
