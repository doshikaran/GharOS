"""Demo household seed loader (PHASES.md Phase 1 work item 8).

Writes `demo_household.build_demo_household()`'s starter graph through the
real, provenance-guarded `FirestoreGraphWriter` — never by writing
directly to Firestore or bypassing the guard, so seeded data is held to
exactly the same standard as ingested data. This is also why this loader
lives in `backend/seeds/` and depends on `app.graph`, rather than the
other way around.

Order matters: every node is written first, then the one supersession
step (which requires the original obligation to already exist), then
every edge (several of which reference the post-supersession obligation
and would otherwise dangle).
"""

from __future__ import annotations

from contracts.graph_types import NodeId

from app.graph.writer import FirestoreGraphWriter
from seeds.demo_household import SeedResult, build_demo_household


def load_demo_household(writer: FirestoreGraphWriter) -> SeedResult:
    """Writes the full demo household graph via `writer`. Idempotent in
    effect if called twice against the same store: `write_node` always
    creates a new version rather than erroring on an existing id, so a
    second call adds new versions rather than corrupting anything — but
    it is meant to be called once against a freshly-seeded store (e.g. a
    per-test-session emulator database).

    Returns:
        The `SeedResult` that was written, so callers (tests, the
        integrity-checker proof) can reference specific seeded ids without
        re-deriving them.
    """
    seed = build_demo_household()

    for node in seed.nodes:
        writer.write_node(node)

    old_obligation_id, new_obligation = seed.supersession
    writer.supersede_node(NodeId(old_obligation_id), new_obligation)

    for edge in seed.edges:
        writer.write_edge(edge)

    return seed
