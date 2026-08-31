"""`FirestoreGraphChangeStream` — the live, shared broadcaster behind
`GET /graph/stream` (PHASES.md Phase 6 E1 work item: "streaming/
subscription endpoint for live mutations").

**Set up once, shared by every connected SSE client** (PHASES.md Phase 6's
own explicit design requirement): one instance of this class opens the 17
real `google.cloud.firestore` `on_snapshot` listeners — one per node
collection (`app.persistence.collections.NODE_TYPE_TO_COLLECTION`) plus the
flat `edges` collection — exactly once, at app composition time
(`app.main`'s lifespan), never per HTTP connection. Every currently
connected client gets its own `asyncio.Queue`; a detected change fans out
to all of them.

**Thread bridge.** Each Firestore `on_snapshot` callback runs on a
Firestore-library-managed background thread (`google.cloud.firestore_v1
.watch.Watch`'s own consumer thread), never the asyncio event loop thread
serving HTTP requests. Pushing directly onto an `asyncio.Queue` from that
thread would not be safe — `asyncio.Queue` assumes single-threaded access
from its owning loop. Every fan-out push instead goes through
`loop.call_soon_threadsafe(queue.put_nowait, event)`, the standard,
correct bridge from a foreign thread into a specific running event loop
(the loop captured once, at `start()` time).

**Only forwards `ADDED`/`MODIFIED`.** `REMOVED` is never forwarded —
nodes/edges are never hard-deleted in this system, only superseded (a
`MODIFIED` on the same document id), so a Firestore-level `REMOVED` change
type here would only ever reflect an internal listener/index artefact,
never a real domain deletion (PHASES.md Phase 6's own explicit rule).
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from typing import Any, Literal

import structlog
from google.cloud import firestore
from google.cloud.firestore_v1.watch import ChangeType, Watch

from app.graph.serialization import build_edge_envelope, build_node_envelope
from app.persistence.collections import EDGES_COLLECTION, NODE_TYPE_TO_COLLECTION

logger = structlog.get_logger(__name__)

_FORWARDED_CHANGE_TYPES = (ChangeType.ADDED, ChangeType.MODIFIED)

_INITIAL_SNAPSHOT_SETTLE_TIMEOUT_SECONDS = 30.0
"""How long `start()` waits for every one of the 17 listeners' initial
"current state" snapshot to arrive and be swallowed (see `_node_callback`'s
docstring) before returning. Blocking here — rather than returning
immediately and racing a caller's first write against an in-flight initial
snapshot — is what makes "a write before subscribing is not replayed"
correct by construction instead of correct-by-favourable-timing.

Against real Firestore every listener's initial snapshot settles in ~1-2s;
against the local emulator, opening ~19 concurrent `on_snapshot` gRPC
streams at once on a loaded dev machine can genuinely take longer, so this
is deliberately generous. It is a safety wait, not a latency SLA."""


@dataclass(frozen=True, slots=True)
class GraphChangeEvent:
    """One live node/edge write, already shaped as `/graph/snapshot`'s own
    per-node/per-edge JSON (`app.graph.serialization.build_node_envelope` /
    `build_edge_envelope`) — the SSE layer (`app.api.graph_router`) only
    has to serialise `payload` to JSON, never re-derive its shape."""

    kind: Literal["node", "edge"]
    payload: dict[str, Any]


class FirestoreGraphChangeStream:
    """Broadcasts live Firestore node/edge writes to every subscribed
    `asyncio.Queue` via one shared set of `on_snapshot` listeners.

    Construct once (dependency-injected at the composition root —
    `app.main`'s lifespan — never a module-level singleton, per
    gharos-standards). Call `start()` exactly once, from within the
    asyncio event loop that will serve SSE connections. Call `stop()` on
    app shutdown to release the underlying Firestore watches.
    """

    def __init__(self, client: firestore.Client) -> None:
        self._client = client
        self._loop: asyncio.AbstractEventLoop | None = None
        self._queues: set[asyncio.Queue[GraphChangeEvent]] = set()
        self._queues_lock = threading.Lock()
        self._watches: list[Watch] = []

    def start(self) -> None:
        """Opens the 17 shared Firestore `on_snapshot` listeners (16 node
        collections + `edges`) and blocks until every one of them has
        received its initial "current state" snapshot (see
        `_node_callback`'s docstring on why that first batch is always
        swallowed, never forwarded).

        Must be called from within a running asyncio event loop — it
        captures `asyncio.get_running_loop()` so later callback-thread
        fan-out can bridge back into it via `call_soon_threadsafe`.

        Blocking here, rather than returning as soon as the watches are
        merely *requested*, removes a real race: without this wait, a
        write issued immediately after `start()` returns could still land
        inside a given collection's still-in-flight initial snapshot and
        be silently swallowed alongside it (a genuinely live write
        mistaken for pre-existing state) — the mirror image of the replay
        bug this design otherwise guards against.

        Raises:
            RuntimeError: called more than once, called with no asyncio
                event loop currently running, or a listener's initial
                snapshot did not settle within
                `_INITIAL_SNAPSHOT_SETTLE_TIMEOUT_SECONDS`.
        """
        if self._loop is not None:
            raise RuntimeError("FirestoreGraphChangeStream.start() called more than once")
        self._loop = asyncio.get_running_loop()

        settled_events: list[threading.Event] = []
        for node_type, collection_name in NODE_TYPE_TO_COLLECTION.items():
            settled = threading.Event()
            watch = self._client.collection(collection_name).on_snapshot(
                self._node_callback(node_type, settled)
            )
            self._watches.append(watch)
            settled_events.append(settled)

        edge_settled = threading.Event()
        edge_watch = self._client.collection(EDGES_COLLECTION).on_snapshot(
            self._make_edge_callback(edge_settled)
        )
        self._watches.append(edge_watch)
        settled_events.append(edge_settled)

        for settled in settled_events:
            if not settled.wait(timeout=_INITIAL_SNAPSHOT_SETTLE_TIMEOUT_SECONDS):
                raise RuntimeError(
                    "FirestoreGraphChangeStream.start(): a listener's initial snapshot did not "
                    f"settle within {_INITIAL_SNAPSHOT_SETTLE_TIMEOUT_SECONDS}s"
                )

        logger.info("graph_change_stream.started", watched_collections=len(self._watches))

    def stop(self) -> None:
        """Cancels every underlying Firestore watch. Idempotent — safe to
        call even if `start()` was never called or `stop()` already ran."""
        for watch in self._watches:
            # `Watch.unsubscribe` ships no parameter/return annotations in
            # google-cloud-firestore's own source (the module is marked
            # py.typed but this method predates the library's annotation
            # coverage — the same gap `app.api.pubsub_receiver` documents
            # for `verify_oauth2_token`). The call itself is real; only the
            # stub coverage is missing.
            watch.unsubscribe()  # type: ignore[no-untyped-call]
        self._watches.clear()
        self._loop = None
        logger.info("graph_change_stream.stopped")

    def subscribe(self) -> asyncio.Queue[GraphChangeEvent]:
        """Registers a new fan-out queue for one connected SSE client.
        Events written *after* this call are delivered to the returned
        queue; nothing already in Firestore before subscribing is
        replayed (that is `/graph/snapshot`'s job, not this one's)."""
        queue: asyncio.Queue[GraphChangeEvent] = asyncio.Queue()
        with self._queues_lock:
            self._queues.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[GraphChangeEvent]) -> None:
        """Removes a disconnected client's queue so it stops receiving
        fan-out and can be garbage-collected — no unbounded growth of dead
        queues over a long-running demo session."""
        with self._queues_lock:
            self._queues.discard(queue)

    # -- Firestore callback thread — never the asyncio loop thread -----------

    def _node_callback(self, node_type: type, settled: threading.Event) -> Any:
        # **The initial-snapshot trap.** Every `on_snapshot` watch's *first*
        # callback invocation delivers the entire current query result as a
        # batch of `ADDED` changes — universal Firestore watch-API behaviour
        # across every client library, not an emulator quirk. Since this
        # broadcaster's listeners are set up once, independently of any
        # client ever subscribing, that first batch is never a live write —
        # forwarding it would replay every pre-existing node to whichever
        # queue happens to be subscribed when it arrives (a real,
        # order-dependent bug this phase's own design requirement
        # explicitly forbids: "a write made before subscribing is NOT
        # replayed"). The first callback unconditionally swallows its batch
        # and sets `settled` — `start()` blocks on every collection's
        # `settled` event before returning, so no write issued after
        # `start()` returns can ever race into this branch.
        seen_first_snapshot = False

        def _on_snapshot(_collection_snapshot: Any, changes: list[Any], _read_time: Any) -> None:
            nonlocal seen_first_snapshot
            if not seen_first_snapshot:
                seen_first_snapshot = True
                settled.set()
                return
            for change in changes:
                if change.type not in _FORWARDED_CHANGE_TYPES:
                    continue
                data = change.document.to_dict()
                if data is None:
                    continue
                payload = build_node_envelope(node_type, change.document.id, data)
                self._publish(GraphChangeEvent(kind="node", payload=payload))

        return _on_snapshot

    def _make_edge_callback(self, settled: threading.Event) -> Any:
        # See `_node_callback`'s docstring — same initial-snapshot trap,
        # same fix, kept as its own closure (rather than a shared instance
        # flag) so it has independent state from every node collection's
        # own watcher.
        seen_first_snapshot = False

        def _on_snapshot(_collection_snapshot: Any, changes: list[Any], _read_time: Any) -> None:
            nonlocal seen_first_snapshot
            if not seen_first_snapshot:
                seen_first_snapshot = True
                settled.set()
                return
            for change in changes:
                if change.type not in _FORWARDED_CHANGE_TYPES:
                    continue
                data = change.document.to_dict()
                if data is None:
                    continue
                payload = build_edge_envelope(change.document.id, data)
                self._publish(GraphChangeEvent(kind="edge", payload=payload))

        return _on_snapshot

    def _publish(self, event: GraphChangeEvent) -> None:
        """Fans `event` out to every currently-connected client's queue,
        bridging from this Firestore callback thread into the asyncio loop
        captured at `start()` time via `call_soon_threadsafe` — never a
        direct cross-thread `queue.put_nowait` call."""
        loop = self._loop
        if loop is None:
            return
        with self._queues_lock:
            queues = tuple(self._queues)
        for queue in queues:
            loop.call_soon_threadsafe(queue.put_nowait, event)
