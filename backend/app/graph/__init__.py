"""GharOS — the real Firestore-backed household knowledge graph (Phase 1,
E1 lead).

Domain-facing repository implementations satisfying every protocol in
`contracts/repositories.py`: `FirestoreGraphReader` (all 14 traversal
operations, spec §5.7), `FirestoreGraphWriter` (provenance-guarded writes
and supersession), `FirestoreGraphIntegrityChecker` (orphans, missing
provenance, dangling edges — spec §16.2), and the narrow
`FirestorePersonRepository` / `FirestoreObligationRepository` /
`FirestoreDecisionRepository` / `FirestorePatternRepository`.

Built on `app.persistence.firestore_store.FirestoreGraphStore` — this
package owns graph *semantics* (what a traversal means), the persistence
package owns Firestore *mechanics* (how a document is stored). Replaces
`app.persistence`'s Phase 0 in-memory stand-in entirely.

Also home to Phase 14's scheduled maintenance jobs (ADR-021, E1 lead):
`pattern_miner.PatternMiner` (A10), `graph_maintainer.GraphMaintainer`
(A11), and `consolidation_service.ConsolidationService`/
`run_nightly_consolidation` (the off-peak orchestrator both run under).
"""

from __future__ import annotations
