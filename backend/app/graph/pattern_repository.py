"""`FirestorePatternRepository` — real, Firestore-backed
`contracts.repositories.PatternRepository`.

Written only by the Pattern Miner (A10), scheduled and support-threshold
gated (spec §15.3) — Phase 14 work. `write_pattern` still runs the
provenance guard: PATTERN nodes carry provenance like every other node
(spec §5.6), even though this protocol is narrower than `GraphWriter`.
"""

from __future__ import annotations

from contracts.graph_types import NodeId, Pattern

from app.persistence.firestore_store import FirestoreGraphStore


class FirestorePatternRepository:
    """Structurally satisfies `contracts.repositories.PatternRepository`."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def all_patterns(self) -> tuple[Pattern, ...]:
        return self._store.all_current_nodes((Pattern,))

    def write_pattern(self, pattern: Pattern) -> NodeId:
        return self._store.put_node(pattern)
