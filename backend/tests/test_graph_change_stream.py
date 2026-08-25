"""`FirestoreGraphChangeStream` — the single most safety-relevant
behavioural claim in Phase 6's design (per the phase's own report
instructions, mirroring Gate 6's CTO review: "watching cold, is it obvious
the graph is being *built*, not replayed?"):

1. a write made *after* subscribing is delivered to a connected client's
   queue before a reasonable timeout;
2. a write made *before* subscribing is **not** replayed into that queue.

Both proven here against the real Firestore emulator (never a mock) via
the real provenance-guarded `writer` fixture, watching real
`on_snapshot` listeners on a real collection — not a simulated event.
"""

from __future__ import annotations

import asyncio
import uuid

import pytest
from contracts.graph_types import Edge, EdgeId, EdgeType, NodeId, Person, PersonRole
from google.cloud import firestore

from app.graph.change_stream import FirestoreGraphChangeStream
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from tests.conftest import make_language_profile, make_provenance

_DELIVERY_TIMEOUT_SECONDS = 10.0
"""Generous but bounded — the Firestore emulator's watch delivery latency
is typically well under a second locally, but CI/cold-start variance
earns a real margin rather than a flaky near-zero timeout."""


def _make_person(node_id: str, display_name: str) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=make_provenance(),
        display_name=display_name,
        aliases=(),
        role=PersonRole.ADULT,
        can_drive=False,
        can_sign=False,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=make_language_profile(),
    )


@pytest.mark.asyncio
async def test_write_after_subscribe_is_delivered(
    firestore_client: firestore.Client, store: FirestoreGraphStore, writer: FirestoreGraphWriter
) -> None:
    change_stream = FirestoreGraphChangeStream(firestore_client)
    change_stream.start()
    try:
        queue = change_stream.subscribe()

        writer.write_node(_make_person("person-live-write", "Kavya"))

        event = await asyncio.wait_for(queue.get(), timeout=_DELIVERY_TIMEOUT_SECONDS)
        assert event.kind == "node"
        assert event.payload["id"] == "person-live-write"
        assert event.payload["type"] == "PERSON"
        assert event.payload["label"] == "Kavya"
    finally:
        change_stream.stop()


@pytest.mark.asyncio
async def test_write_before_subscribe_is_not_replayed(
    firestore_client: firestore.Client, store: FirestoreGraphStore, writer: FirestoreGraphWriter
) -> None:
    # Written BEFORE the change stream even starts watching.
    writer.write_node(_make_person("person-pre-existing", "Written before subscribing"))

    change_stream = FirestoreGraphChangeStream(firestore_client)
    change_stream.start()
    try:
        queue = change_stream.subscribe()

        # Give the listener a real moment to have (wrongly) delivered a
        # replay if it were going to — then prove the queue is genuinely
        # empty, not just "not yet delivered".
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=2.0)

        # And the stream is still live for genuinely new writes made
        # after subscribing — proving the empty queue above wasn't just a
        # broken/dead listener.
        writer.write_node(_make_person("person-live-write-2", "Written after subscribing"))
        event = await asyncio.wait_for(queue.get(), timeout=_DELIVERY_TIMEOUT_SECONDS)
        assert event.payload["id"] == "person-live-write-2"
    finally:
        change_stream.stop()


@pytest.mark.asyncio
async def test_edge_write_is_delivered_as_edge_event(
    firestore_client: firestore.Client, store: FirestoreGraphStore, writer: FirestoreGraphWriter
) -> None:
    writer.write_node(_make_person("person-edge-from", "From"))
    writer.write_node(_make_person("person-edge-to", "To"))

    change_stream = FirestoreGraphChangeStream(firestore_client)
    change_stream.start()
    try:
        queue = change_stream.subscribe()

        writer.write_edge(
            Edge(
                id=EdgeId("edge-conflict-test"),
                provenance=make_provenance(),
                edge_type=EdgeType.CONFLICTS_WITH,
                from_id=NodeId("person-edge-from"),
                to_id=NodeId("person-edge-to"),
            )
        )

        event = await asyncio.wait_for(queue.get(), timeout=_DELIVERY_TIMEOUT_SECONDS)
        assert event.kind == "edge"
        assert event.payload["id"] == "edge-conflict-test"
        assert event.payload["is_conflict"] is True
    finally:
        change_stream.stop()


@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery_to_that_queue(
    firestore_client: firestore.Client, store: FirestoreGraphStore, writer: FirestoreGraphWriter
) -> None:
    change_stream = FirestoreGraphChangeStream(firestore_client)
    change_stream.start()
    try:
        queue = change_stream.subscribe()
        change_stream.unsubscribe(queue)

        writer.write_node(_make_person("person-after-unsubscribe", "Should not arrive"))

        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), timeout=2.0)
    finally:
        change_stream.stop()


@pytest.mark.asyncio
async def test_two_subscribers_both_receive_the_same_write(
    firestore_client: firestore.Client, store: FirestoreGraphStore, writer: FirestoreGraphWriter
) -> None:
    change_stream = FirestoreGraphChangeStream(firestore_client)
    change_stream.start()
    try:
        queue_a = change_stream.subscribe()
        queue_b = change_stream.subscribe()

        writer.write_node(_make_person("person-fanout", "Fanout"))

        event_a = await asyncio.wait_for(queue_a.get(), timeout=_DELIVERY_TIMEOUT_SECONDS)
        event_b = await asyncio.wait_for(queue_b.get(), timeout=_DELIVERY_TIMEOUT_SECONDS)
        assert event_a.payload["id"] == "person-fanout"
        assert event_b.payload["id"] == "person-fanout"
    finally:
        change_stream.stop()


def test_start_called_twice_raises() -> None:
    client = firestore.Client(project=f"gharos-test-{uuid.uuid4().hex[:16]}", database="(default)")
    try:
        change_stream = FirestoreGraphChangeStream(client)

        async def _start_twice() -> None:
            change_stream.start()
            with pytest.raises(RuntimeError, match="called more than once"):
                change_stream.start()

        asyncio.run(_start_twice())
        change_stream.stop()
    finally:
        client.close()  # type: ignore[no-untyped-call]
