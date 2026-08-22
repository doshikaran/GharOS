# ADR-001: Firestore layout for nodes and edges

**Status:** accepted
**Phase:** 0
**Date:** 2026-08-22

## Context

The Household Knowledge Graph (spec §5) needs a Firestore layout that
supports: per-type-safe node storage, bidirectional edge traversal
(`neighbours` from either end), the fourteen traversal operations in
spec §5.7, and the provenance-guard write path (PHASES.md Phase 1). Firestore
is document-shaped, not graph-native, so the layout has to earn traversal
performance rather than assume it.

## Decision

- **One top-level collection per node type**, e.g. `persons`, `obligations`,
  `constraints`, `ledger_events`, `purchase_items`, `decisions`,
  `council_positions`, etc. — collection name is the lowercase, pluralised
  node type. Document ID = `NodeId`. Each document embeds a `provenance` map
  matching `contracts.graph_types.Provenance` exactly (same field names),
  plus a `superseded_at` field that is set, never deleted, on supersession
  (writes create versions — PHASES.md §2.2).
- **One flat top-level `edges` collection** for every edge, regardless of
  type. Each document embeds `edge_type`, `from_id`, `to_id`, `provenance`,
  and `metadata`. Composite indexes on `(from_id, edge_type)` and
  `(to_id, edge_type)` support `neighbours()` in both directions without
  duplicating edge documents.
- **No subcollections for edges.** Edges are not nested under their source
  node's document.
- `blast_radius` and `path` are implemented as repository-layer BFS/DFS over
  `edges`, bounded by a depth parameter — acceptable for demo-scale graphs
  (hundreds of nodes); see the open question this ADR does not resolve,
  below.

## Alternatives considered

1. **Subcollections under each node for its outgoing edges.** Rejected:
   reverse traversal (`to_id` lookups) would need a mirrored subcollection
   maintained in lockstep, doubling writes and doubling the surface for the
   provenance guard to be bypassed.
2. **A single `nodes` collection with a `type` discriminator field instead
   of per-type collections.** Rejected: per-type collections give simpler,
   type-safe composite indexes and let `contracts.repositories` expose
   narrowly-typed repository protocols (`PersonRepository`,
   `ObligationRepository`, ...) instead of one giant generic node
   repository with runtime type-checking at every call site.

## Consequences

- Traversal correctness is straightforward to reason about and test
  (Gate 1: "all 14 traversals implemented and tested").
- Firestore does not enforce edge referential integrity — the Graph
  Integrity Checker (`contracts.repositories.GraphIntegrityChecker`) is
  therefore load-bearing, not a nice-to-have; it is how dangling edges
  (`from_id`/`to_id` pointing at a superseded or missing node) get caught.
- **Open question this ADR does not resolve** (spec §27.2 Q8): whether
  Firestore's multi-hop traversal performance holds at demo graph size, or
  whether a graph-native store becomes necessary. Revisit in Phase 1's
  own ADR once traversal latency is measured against seeded demo data —
  this ADR only fixes the *default* layout, not a final performance
  verdict.
