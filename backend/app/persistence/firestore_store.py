"""`FirestoreGraphStore` — the low-level Firestore adapter every concrete
repository in `app.graph` is built on (ADR-001 layout: one collection per
node type, one flat `edges` collection, composite indexes on
`(from_id, edge_type)` / `(to_id, edge_type)` — declared in
`backend/migrations/firestore_indexes.py`).

This is infrastructure, not domain logic: it knows how to durably store
and retrieve nodes/edges and how versioning/supersession is mechanically
implemented, but it has no opinion on what a traversal *means* — that
belongs to `app.graph.reader.FirestoreGraphReader` and friends.

Every public method here calls `app.persistence.provenance_guard.validate_provenance`
before any network write, and validation happens before the Firestore
transaction is even opened — an invalid write never partially lands.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from contracts.graph_types import Edge, EdgeId, EdgeType, NodeId
from google.cloud import firestore
from google.cloud.firestore_v1.base_query import FieldFilter

from app.persistence.codecs.edges import decode_edge, encode_edge
from app.persistence.codecs.nodes import decode_node, encode_node
from app.persistence.collections import (
    EDGES_COLLECTION,
    NODE_INDEX_COLLECTION,
    NODE_TYPE_TO_COLLECTION,
    VERSIONS_SUBCOLLECTION,
    collection_for,
    node_type_for_collection,
)
from app.persistence.provenance_guard import validate_provenance

_VERSION_SEQ_FIELD = "_version_seq"
"""Internal bookkeeping field on stored node documents — monotonically
increasing per node id, used to order the immutable `versions`
subcollection and to compute the next version number. Never part of the
domain shape in `contracts.graph_types`; stripped from nothing (decode
functions only read the keys they know about, so its presence is
harmless), but never surfaced through any repository return type either.
"""


class FirestoreGraphStore:
    """Durable node/edge storage. Constructed with an injected
    `firestore.Client` — never a module-level singleton (gharos-standards
    skill, dependency injection rule)."""

    def __init__(self, client: firestore.Client) -> None:
        self._client = client

    # -- nodes ---------------------------------------------------------------

    def put_node(self, node: Any) -> NodeId:
        """Validates provenance, then writes `node` as a new version.

        Every write — first write or Nth write for the same id — creates a
        new immutable entry in that id's `versions` subcollection before
        (in the same transaction as) updating the top-level "current
        version" document. Raises `ProvenanceMissing` before any network
        call if `node`'s provenance is incomplete.
        """
        validate_provenance(node)
        node_type = type(node)
        collection_name = collection_for(node_type)
        node_id = str(node.id)
        data = encode_node(node)

        doc_ref = self._client.collection(collection_name).document(node_id)
        index_ref = self._client.collection(NODE_INDEX_COLLECTION).document(node_id)
        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> None:
            current_snapshot = doc_ref.get(transaction=txn)
            version_seq = 1
            if current_snapshot.exists:
                version_seq = int(current_snapshot.get(_VERSION_SEQ_FIELD) or 0) + 1
            payload = dict(data)
            payload[_VERSION_SEQ_FIELD] = version_seq
            txn.set(doc_ref, payload)
            version_ref = doc_ref.collection(VERSIONS_SUBCOLLECTION).document(str(version_seq))
            txn.set(version_ref, payload)
            txn.set(index_ref, {"collection": collection_name})

        _run(transaction)
        return NodeId(node_id)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        """Marks the current version stored at `old_node_id` superseded
        (setting `provenance.superseded_at`, once only — never overwritten
        if already set) and writes `new_node` as a new current version.

        Provenance on `new_node` is validated *before* the old node is
        touched — a rejected supersession never mutates the prior version
        (PHASES.md Phase 1 work item 3).

        Raises:
            ProvenanceMissing: `new_node`'s provenance is incomplete.
        """
        validate_provenance(new_node)
        new_collection = collection_for(type(new_node))
        new_id = str(new_node.id)
        new_data = encode_node(new_node)
        new_doc_ref = self._client.collection(new_collection).document(new_id)
        new_index_ref = self._client.collection(NODE_INDEX_COLLECTION).document(new_id)
        old_index_ref = self._client.collection(NODE_INDEX_COLLECTION).document(str(old_node_id))

        transaction = self._client.transaction()

        @firestore.transactional
        def _run(txn: firestore.Transaction) -> None:
            old_index_snap = old_index_ref.get(transaction=txn)
            old_doc_ref = None
            old_snap = None
            if old_index_snap.exists:
                old_collection = old_index_snap.get("collection")
                old_doc_ref = self._client.collection(old_collection).document(str(old_node_id))
                old_snap = old_doc_ref.get(transaction=txn)

            new_current_snap = new_doc_ref.get(transaction=txn)
            new_version_seq = (
                int(new_current_snap.get(_VERSION_SEQ_FIELD) or 0) + 1 if new_current_snap.exists else 1
            )

            if old_snap is not None and old_snap.exists and old_doc_ref is not None:
                old_payload = dict(old_snap.to_dict() or {})
                provenance = dict(old_payload.get("provenance") or {})
                if provenance.get("superseded_at") is None:
                    provenance["superseded_at"] = datetime.now(UTC)
                    old_payload["provenance"] = provenance
                    old_version_seq = int(old_payload.get(_VERSION_SEQ_FIELD) or 0) + 1
                    old_payload[_VERSION_SEQ_FIELD] = old_version_seq
                    txn.set(old_doc_ref, old_payload)
                    old_version_ref = old_doc_ref.collection(VERSIONS_SUBCOLLECTION).document(
                        str(old_version_seq)
                    )
                    txn.set(old_version_ref, old_payload)

            new_payload = dict(new_data)
            new_payload[_VERSION_SEQ_FIELD] = new_version_seq
            txn.set(new_doc_ref, new_payload)
            new_version_ref = new_doc_ref.collection(VERSIONS_SUBCOLLECTION).document(str(new_version_seq))
            txn.set(new_version_ref, new_payload)
            txn.set(new_index_ref, {"collection": new_collection})

        _run(transaction)
        return NodeId(new_id)

    def get_node(self, node_id: NodeId) -> Any | None:
        """Returns the current (possibly superseded) version of `node_id`,
        or `None` if it was never written."""
        collection_name = self._resolve_collection(node_id)
        if collection_name is None:
            return None
        snap = self._client.collection(collection_name).document(str(node_id)).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        if data is None:
            return None
        node_type = node_type_for_collection(collection_name)
        return decode_node(node_type, str(node_id), data)

    def node_history(self, node_id: NodeId) -> tuple[Any, ...]:
        """All versions ever written for `node_id`, oldest first. Never
        empty for an id that was written at least once; empty for an id
        that was never written. Nothing is ever deleted from this list."""
        collection_name = self._resolve_collection(node_id)
        if collection_name is None:
            return ()
        node_type = node_type_for_collection(collection_name)
        doc_ref = self._client.collection(collection_name).document(str(node_id))
        versions = doc_ref.collection(VERSIONS_SUBCOLLECTION).order_by(_VERSION_SEQ_FIELD).stream()
        result: list[Any] = []
        for version_snap in versions:
            data = version_snap.to_dict()
            if data is not None:
                result.append(decode_node(node_type, str(node_id), data))
        return tuple(result)

    def all_current_nodes(self, node_types: tuple[type, ...] | None = None) -> tuple[Any, ...]:
        """Every current node version across the requested `node_types`
        (all 16 registered types if `None`). Demo-scale graph size (spec
        §27.2 open question #8) makes a full per-collection stream
        acceptable for Phase 1 — see ADR-001."""
        types_to_scan = node_types if node_types is not None else tuple(NODE_TYPE_TO_COLLECTION.keys())
        result: list[Any] = []
        for node_type in types_to_scan:
            collection_name = collection_for(node_type)
            for snap in self._client.collection(collection_name).stream():
                data = snap.to_dict()
                if data is not None:
                    result.append(decode_node(node_type, snap.id, data))
        return tuple(result)

    def _resolve_collection(self, node_id: NodeId) -> str | None:
        index_snap = self._client.collection(NODE_INDEX_COLLECTION).document(str(node_id)).get()
        if not index_snap.exists:
            return None
        collection_name = index_snap.get("collection")
        return str(collection_name) if collection_name is not None else None

    def node_exists(self, node_id: NodeId) -> bool:
        """Whether *some* document is currently stored at `node_id` —
        deliberately weaker than `get_node(...) is not None`: it does not
        attempt to decode the document into a typed dataclass, so it
        cannot itself crash on a structurally corrupted document. Used by
        `FirestoreGraphIntegrityChecker`'s dangling-edge check, whose job
        is to detect exactly that kind of corruption rather than raise on
        it."""
        collection_name = self._resolve_collection(node_id)
        if collection_name is None:
            return False
        return self._client.collection(collection_name).document(str(node_id)).get().exists

    def all_current_node_documents(self) -> tuple[tuple[type, str, dict[str, Any] | None], ...]:
        """Raw (undecoded) scan across every node collection — yields
        `(node_type, doc_id, raw_document_dict_or_None)` triples without
        ever calling a per-type decoder. Used by integrity-style checks
        (`FirestoreGraphReader.unexplained`,
        `FirestoreGraphIntegrityChecker`) that must find and report
        structurally corrupted documents (e.g. `provenance: None`) rather
        than crash decoding them — `all_current_nodes` above is for normal
        domain reads, which are entitled to assume the write guard already
        did its job and to fail loudly (not silently) if that assumption
        is ever wrong."""
        result: list[tuple[type, str, dict[str, Any] | None]] = []
        for node_type, collection_name in NODE_TYPE_TO_COLLECTION.items():
            for snap in self._client.collection(collection_name).stream():
                result.append((node_type, snap.id, snap.to_dict()))
        return tuple(result)

    def all_edge_documents(self) -> tuple[tuple[str, dict[str, Any] | None], ...]:
        """Raw (undecoded) scan across the `edges` collection — see
        `all_current_node_documents` for why this exists alongside the
        typed `all_edges`."""
        return tuple((snap.id, snap.to_dict()) for snap in self._client.collection(EDGES_COLLECTION).stream())

    # -- edges -----------------------------------------------------------------

    def put_edge(self, edge: Edge) -> None:
        """Validates provenance, then writes `edge` to the flat top-level
        `edges` collection (ADR-001 — never a subcollection).

        Raises:
            ProvenanceMissing: `edge`'s provenance is incomplete.
        """
        validate_provenance(edge)
        data = encode_edge(edge)
        self._client.collection(EDGES_COLLECTION).document(str(edge.id)).set(data)

    def get_edge(self, edge_id: EdgeId) -> Edge | None:
        snap = self._client.collection(EDGES_COLLECTION).document(str(edge_id)).get()
        if not snap.exists:
            return None
        data = snap.to_dict()
        return None if data is None else decode_edge(snap.id, data)

    def all_edges(self) -> tuple[Edge, ...]:
        return tuple(
            decode_edge(snap.id, data)
            for snap in self._client.collection(EDGES_COLLECTION).stream()
            if (data := snap.to_dict()) is not None
        )

    def edges_from(self, node_id: NodeId, edge_type: EdgeType | None = None) -> tuple[Edge, ...]:
        """Edges where `from_id == node_id`, optionally filtered by
        `edge_type`. Backed by the `(from_id, edge_type)` composite index
        (`backend/migrations/firestore_indexes.py`)."""
        query = self._client.collection(EDGES_COLLECTION).where(
            filter=FieldFilter("from_id", "==", str(node_id))
        )
        if edge_type is not None:
            query = query.where(filter=FieldFilter("edge_type", "==", edge_type.value))
        return tuple(
            decode_edge(snap.id, data) for snap in query.stream() if (data := snap.to_dict()) is not None
        )

    def edges_to(self, node_id: NodeId, edge_type: EdgeType | None = None) -> tuple[Edge, ...]:
        """Edges where `to_id == node_id`, optionally filtered by
        `edge_type`. Backed by the `(to_id, edge_type)` composite index."""
        query = self._client.collection(EDGES_COLLECTION).where(
            filter=FieldFilter("to_id", "==", str(node_id))
        )
        if edge_type is not None:
            query = query.where(filter=FieldFilter("edge_type", "==", edge_type.value))
        return tuple(
            decode_edge(snap.id, data) for snap in query.stream() if (data := snap.to_dict()) is not None
        )
