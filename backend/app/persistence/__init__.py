"""GharOS — Firestore persistence layer (Phase 1, E1 lead).

Low-level Firestore adapter code: client construction (dependency
injection, no module-level singleton — `firestore_client.py`), the
node/edge collection layout (`collections.py`, per
`docs/adr/001-firestore-edge-layout.md`), dataclass<->Firestore-document
codecs (`codecs/`), the provenance write guard (`provenance_guard.py` —
safety invariant #3), the durable node/edge store with versioning and
supersession (`firestore_store.py`), and the durable idempotency store
(`idempotency_store.py`, spec §19.1).

This package replaces Phase 0's in-memory stub repositories entirely —
nothing here is a stand-in. The higher-level, protocol-facing repository
implementations (`GraphReader`, `GraphWriter`, `PersonRepository`, ...)
that domain code actually depends on live in `app.graph`, built on top of
`FirestoreGraphStore` from this package (hexagonal / ports-and-adapters —
`app.graph` is the domain-facing layer, this package is the
infrastructure-facing one).
"""

from __future__ import annotations
