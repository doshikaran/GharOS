"""Shared builders for the Phase 15 demo-seed segments.

Mirrors `seeds.demo_household`'s own `_prov` / `_edge` helpers so segment
data is shaped identically to Phase 1's — every node and edge carries full,
valid `Provenance` (safety invariant #3), so `unexplained(scope)` stays
empty and `FirestoreGraphIntegrityChecker` stays clean on the aggregated
graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from contracts.graph_types import (
    AgentId,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Provenance,
    SourceRef,
)

from seeds.demo_household import NOW

__all__ = [
    "NOW",
    "SEED_AGENT",
    "Segment",
    "ambiguous_prov",
    "days",
    "edge",
    "language_profile",
    "months_ago",
    "prov",
]

SEED_AGENT = AgentId("A7")
"""Graph Builder (spec §15) — the agent a real durable graph write runs
under; seed data uses the same identity a real write would, per
`seeds.demo_household`'s own convention."""


def days(count: float) -> timedelta:
    return timedelta(days=count)


def months_ago(count: int) -> datetime:
    """`NOW` shifted back `count` 30-day months — good enough for a demo
    dataset whose only requirement is "roughly three months of history"."""
    return NOW - timedelta(days=30 * count)


def prov(
    *,
    source_document_id: str,
    region: str,
    derivation: Derivation = Derivation.EXTRACTED,
    confidence: float = 0.9,
) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=SourceRef(source_document_id=NodeId(source_document_id), region=region),
        confidence=confidence,
        deriving_agent=SEED_AGENT,
        created_at=NOW,
    )


def ambiguous_prov(*, source_document_id: str, region: str, confidence: float = 0.5) -> Provenance:
    """`Derivation.AMBIGUOUS` with a real `source_ref` — permitted by the
    contract (`Provenance.__post_init__` only forbids a `None` source_ref
    for EXTRACTED/INFERRED). Used for the deliberately-ambiguous escalation
    document, where the evidence genuinely points more than one way but is
    still openable at a specific region."""
    return Provenance(
        derivation=Derivation.AMBIGUOUS,
        source_ref=SourceRef(source_document_id=NodeId(source_document_id), region=region),
        confidence=confidence,
        deriving_agent=SEED_AGENT,
        created_at=NOW,
    )


def edge(
    edge_id: str,
    edge_type: EdgeType,
    from_id: NodeId,
    to_id: NodeId,
    *,
    source_document_id: str,
    region: str = "derived",
    derivation: Derivation = Derivation.INFERRED,
    confidence: float = 0.88,
) -> Edge:
    return Edge(
        id=EdgeId(edge_id),
        provenance=prov(
            source_document_id=source_document_id,
            region=region,
            derivation=derivation,
            confidence=confidence,
        ),
        edge_type=edge_type,
        from_id=from_id,
        to_id=to_id,
    )


def language_profile(primary: str) -> LanguageProfile:
    return LanguageProfile(
        primary_language=primary,
        languages_understood=("hi", "en", "mr") if primary == "mr" else ("hi", "en"),
        script_preference="devanagari" if primary in ("hi", "mr") else "latin",
        code_mixing_profile="hi-en",
        formality_preference="informal",
        literacy_mode=LiteracyMode.BOTH,
    )


@dataclass(frozen=True, slots=True)
class Segment:
    """One slice of the demo dataset — plain data, no I/O."""

    nodes: tuple[object, ...] = ()
    edges: tuple[Edge, ...] = field(default_factory=tuple)
