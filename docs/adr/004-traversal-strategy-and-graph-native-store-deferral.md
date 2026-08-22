# ADR-004: Traversal strategy, and deferring a graph-native store

**Status:** accepted
**Phase:** 1
**Date:** 2026-08-22

## Context

ADR-001 fixed the Firestore layout (one collection per node type, one flat `edges` collection, composite indexes on `(from_id, edge_type)`/`(to_id, edge_type)`) but explicitly left open whether Firestore's traversal performance would hold at demo graph size, or whether a graph-native store would be needed (spec §27.2 open question #8). Phase 1 now has a real implementation of all 14 traversal operations (spec §5.7) against the real Firestore emulator, so this ADR closes that open question with actual evidence rather than speculation.

## Decision

- **Single-hop operations** (`neighbours`, `load`, `series`, `history`, `concession_ledger`, `expected_but_absent`, `effort_evidence`) query the composite indexes directly — one indexed Firestore query per call, no in-memory graph walk. This is the common case and it's O(result size), not O(graph size).
- **Multi-hop operations** (`path`, `blast_radius`) pull the full edge set once per call via a single collection read (`FirestoreGraphStore.all_edges()`) and walk it in memory (BFS/DFS, depth-bounded for `blast_radius`). Verified against the Phase 1 seed graph (36 nodes / 46 edges) with no measurable latency concern.
- **A graph-native store is explicitly deferred, not adopted.** At the sizes this project ever needs to demonstrate (spec §26: "hundreds of nodes" for the demo dataset), pulling the full edge collection into memory once per multi-hop call is fast and simple, and avoids taking on a second stateful service (with its own auth, its own emulator-or-not story, its own place in the deployment diagram) for a problem Firestore does not actually have yet at this scale.
- **The exit condition for revisiting this** is explicit and measurable, not vibes-based: if a future phase's seed data grows past roughly 2,000 edges, or `path`/`blast_radius` p95 latency exceeds ~500ms against real (non-emulator) Firestore, that is the trigger to open a new ADR evaluating a graph-native store (e.g. a managed graph database, or a pre-computed adjacency cache). Until one of those conditions is hit, this decision stands.

## Alternatives considered

1. **Adopt a graph-native store now** (e.g. a managed graph database as an "optional if genuinely earned" service per spec §21.3). Rejected for Phase 1: spec §21.3 is explicit that "every service must be defensible in one sentence" and "do not add services for diagram sophistication" — there is no current evidence Firestore is the bottleneck, so adding a second stateful service now would violate that discipline, not honor it.
2. **Pre-compute and cache adjacency lists** to avoid the full-edge-collection read on every multi-hop call. Rejected for now as premature optimization — Phase 1's measured behavior against the seed graph shows no latency problem to solve yet, and caching introduces its own staleness/invalidation surface that would need its own design (when does the cache get invalidated relative to a versioned write?). Revisit if the exit condition above is triggered.
3. **Implement rich named-subgraph scope semantics now** (e.g. "the Ledger subgraph" as a first-class scope value for `conflicts`/`unexplained`/`unverified`, anticipating the Council's Phase 12 requirement for mutually-distinct T0 subgraph scopes). Deferred, not rejected — Phase 1 implements `scope` as `"all"` vs. a single restricting `NodeId`, which is sufficient for every Phase 1 gate requirement. Named-subgraph scoping is real future work, tracked as a forward-looking item for Phase 12 rather than Phase 1 debt, since nothing in Phase 1's own scope needs it.

## Consequences

- No new infrastructure service enters the architecture diagram (`docs/diagrams/06-deployment.md` stays accurate as-is).
- `path`/`blast_radius` read the full `edges` collection on every call — this is a known, deliberate, and currently-fine cost. A future phase adding tens of thousands of edges without revisiting this ADR would be a real risk; the exit condition above exists so that risk has a named trigger instead of being discovered by surprise during demo rehearsal (PHASES.md Phase 15's explicit fear).
- Named-subgraph scope semantics remain unimplemented; Phase 12 (Council) is where this becomes load-bearing (Gate 12: "mutually distinct T0 subgraph scopes — enforced, not conventional") and must design real scope semantics before Council specialists can be correctly isolated. Flagging this now so it doesn't surprise whoever picks up Phase 12.
