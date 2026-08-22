"""GharOS backend settings — single source of truth for environment
configuration (gharos-standards skill, rule 8: no secrets in code, env vars
via a single settings module).

Field names match `.env.example` at the repo root exactly. Local development
reads `backend/.env` (never committed); Cloud Run reads real environment
variables injected at deploy time.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed application settings, loaded once and cached.

    Every field mirrors a variable in `.env.example`. Add a field here
    whenever a variable is added there — the two must never drift apart.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # GCP project
    gcp_project_id: str = ""
    gcp_region: str = "asia-south1"

    # Firestore
    firestore_emulator_host: str = "localhost:8080"
    firestore_database: str = "(default)"

    # Pub/Sub
    pubsub_emulator_host: str = "localhost:8085"
    pubsub_topic_prefix: str = "gharos-"

    # Pub/Sub push verification (app.api.pubsub_receiver) — the identity
    # Cloud Scheduler -> Pub/Sub push requests must present via a signed
    # OIDC bearer token, wired up post-deploy by infra/pubsub_topics.sh
    # once the deployed service URL is known. Empty = verification
    # skipped with a logged warning (local/emulator dev path, where there
    # is no push subscription and therefore no token to check); a real
    # deployment sets both once infra/pubsub_topics.sh has run against the
    # live service.
    pubsub_push_service_account_email: str = ""
    pubsub_push_audience: str = ""

    # Vertex AI / Gemini
    #
    # Pinned publisher-model versions, not the "-latest" aliases: live-tested
    # against the real `blissful-trail-506312-t0` project in `asia-south1`
    # (Phase 2, `reasoning/gemini_client.py`) and confirmed the "-latest"
    # aliases 404 on Vertex AI's *regional* endpoint (they only resolve via
    # the "global" endpoint) while pinned versions resolve regionally for
    # whichever models this project's region has enabled. `gemini-2.5-flash`
    # is confirmed live-working in `asia-south1` for this project;
    # `gemini-2.5-pro` is the correct canonical Pro-tier model id but is not
    # yet enabled for this project in `asia-south1` specifically (confirmed
    # 404 there; confirmed working via the "global" location) — a regional
    # Model Garden availability gap, not a naming defect. See
    # `docs/DEPLOYMENT_PROOF.md` / the Phase 2 report for the full finding.
    vertex_ai_location: str = "asia-south1"
    gemini_model_flash: str = "gemini-2.5-flash"
    gemini_model_pro: str = "gemini-2.5-pro"

    # CORS — the frontend (gharos-web) and backend (gharos-api) deploy as
    # two separate Cloud Run services with two separate origins, so the
    # browser enforces CORS on every cross-origin fetch the frontend makes
    # (e.g. the /status page's health/gemini-ping/adk-demo checks). Comma-
    # separated exact origins, no wildcard in any real deployment — an
    # allow-all origin policy is never acceptable once T3+ write endpoints
    # exist, and there is no reason to start the habit now. Empty (the
    # local-dev default) means FastAPI's CORSMiddleware is not installed at
    # all — `uv run uvicorn` + `pnpm dev` talk to each other same-origin-
    # equivalent via explicit ports during local development and need no
    # CORS handling. Set for real by infra/deploy_backend.sh once
    # gharos-web's URL is known (mirrors how infra/pubsub_topics.sh wires
    # PUBSUB_PUSH_AUDIENCE once gharos-api's own URL is known).
    cors_allowed_origins: str = ""

    # App
    env: str = "local"
    log_level: str = "INFO"
    budget_alert_threshold_usd: float = 25.0

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        """`cors_allowed_origins` parsed into a list, empty entries and
        surrounding whitespace stripped. Empty input yields an empty list —
        `app.main` treats that as "do not install CORSMiddleware at all",
        not as "allow every origin"."""
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the process-wide cached Settings instance.

    Cached rather than a module-level singleton so tests can bypass the
    cache by constructing `Settings(...)` directly with overrides.
    """
    return Settings()
