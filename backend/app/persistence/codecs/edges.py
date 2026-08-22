"""Encode/decode codec for `contracts.graph_types.Edge` — the flat
top-level `edges` collection (ADR-001)."""

from __future__ import annotations

from typing import Any

from contracts.graph_types import Edge, EdgeId, EdgeType, NodeId

from app.persistence.codecs.common import decode_provenance, encode_provenance


def encode_edge(edge: Edge) -> dict[str, Any]:
    return {
        "id": str(edge.id),
        "provenance": encode_provenance(edge.provenance),
        "edge_type": edge.edge_type.value,
        "from_id": str(edge.from_id),
        "to_id": str(edge.to_id),
        "metadata": dict(edge.metadata),
    }


def decode_edge(doc_id: str, data: dict[str, Any]) -> Edge:
    return Edge(
        id=EdgeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        edge_type=EdgeType(data["edge_type"]),
        from_id=NodeId(data["from_id"]),
        to_id=NodeId(data["to_id"]),
        metadata=dict(data["metadata"]),
    )
