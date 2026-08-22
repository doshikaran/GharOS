"""GharOS backend — FastAPI application entrypoint.

Phase 0: a minimal app exposing `/health` only, matching the Procfile's
`app.main:app` target (`backend/Procfile`, owned by E3). Routers for the
graph, agents, and tools are added by their owning roles in later phases —
this module stays thin; it wires, it does not implement.
"""

from __future__ import annotations

from fastapi import FastAPI

from app.settings import get_settings

app = FastAPI(title="GharOS backend")


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe. Returns process status only — no I/O, no auth."""
    return {"status": "ok"}


@app.get("/health/config")
def health_config() -> dict[str, str]:
    """Diagnostic endpoint confirming settings load correctly, without ever
    echoing secret values (there are none in this settings model, but the
    pattern is to report presence/shape, not raw values)."""
    settings = get_settings()
    return {"env": settings.env, "gcp_region": settings.gcp_region}
