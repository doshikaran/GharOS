"""Firestore schema/index migrations for the household knowledge graph
(Phase 1, E1 lead).

`firestore_indexes.py` declares the composite indexes ADR-001 calls for
(`edges(from_id, edge_type)` / `edges(to_id, edge_type)`) and provides
`apply_indexes` to create them against a real Firestore project via the
Admin API. Not run against the emulator (no Admin API surface there) and
not run against real GCP yet (`docs/DEBT.md` DEBT-001 — no live GCP
billing) — see that module's docstring."""

from __future__ import annotations
