"""GharOS backend — HTTP-facing routers beyond the core `app.main` app.

Shared by two roles this phase (see each module's own docstring for
ownership): `pubsub_receiver.py` (E3 — Pub/Sub push ingestion) and, as of
Phase 2, `debug.py` (E2 — diagnostics). Each module owns its own
`APIRouter`; `app.main` wires them in with `app.include_router(...)`.
"""

from __future__ import annotations
