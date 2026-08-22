"""Firestore client construction — dependency injection, not a
module-level singleton (gharos-standards skill: "no module-level
singletons holding I/O").

Every repository in `app.persistence` / `app.graph` takes a
`google.cloud.firestore.Client` in its constructor; nothing in this
codebase imports `google.cloud.firestore` at module scope and reaches for
a process-wide client. `create_firestore_client` is the one function that
constructs one, and it is called explicitly at the composition root
(`backend/app/main.py`'s future DI wiring, or a test fixture) — never
implicitly on import.
"""

from __future__ import annotations

import os

from google.cloud import firestore

from app.settings import Settings

_LOCAL_FALLBACK_PROJECT_ID = "gharos-local"
"""Used only when `Settings.gcp_project_id` is unset (local/emulator dev —
`.env.example` leaves `GCP_PROJECT_ID` blank on purpose) and
`FIRESTORE_EMULATOR_HOST` is set, so the emulator has *some* project id to
key its in-memory database on. Never used against real Firestore — a real
deployment always sets `GCP_PROJECT_ID` (Cloud Run injects it)."""


def create_firestore_client(settings: Settings) -> firestore.Client:
    """Builds a `firestore.Client` from typed settings.

    Against the Firestore emulator (`FIRESTORE_EMULATOR_HOST` set — the
    client library itself reads that env var), `project` only needs to be
    *some* stable string. Against real Firestore, `settings.gcp_project_id`
    must be set (Cloud Run injects `GCP_PROJECT_ID`) — an empty project id
    there is a misconfiguration, not a fallback case, so it is not silently
    substituted.
    """
    project_id = settings.gcp_project_id
    if not project_id:
        if os.environ.get("FIRESTORE_EMULATOR_HOST"):
            project_id = _LOCAL_FALLBACK_PROJECT_ID
        else:
            raise ValueError(
                "gcp_project_id is unset and FIRESTORE_EMULATOR_HOST is not set — "
                "refusing to guess a project id against real Firestore"
            )
    return firestore.Client(project=project_id, database=settings.firestore_database)
