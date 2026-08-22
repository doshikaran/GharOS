"""The demo household seed loader (Phase 1, E1 lead) — writes a starter
graph through the real provenance-guarded `FirestoreGraphWriter`
(`app.graph.writer`), never by bypassing it, so seeded data is held to the
same standard as ingested data.

`demo_household.py` builds the graph (data only, no I/O);
`seed_loader.py` writes it."""

from __future__ import annotations
