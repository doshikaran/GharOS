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

    # Pro-tier calls resolve through a SEPARATE location from Flash
    # (ModelRouter, `reasoning/model_router.py`) — resolved DEBT-003
    # (Phase 2/3), see ADR-010. `gemini-2.5-pro` 404s regionally in
    # `asia-south1` for this project (confirmed live, ~15 model-id
    # variants tried) but works via Vertex AI's "global" location; Flash
    # stays regional for latency, since it has no such gap. If this
    # project's Pro-tier Model Garden access is ever granted regionally,
    # set this to match `VERTEX_AI_LOCATION` instead of overriding it here.
    vertex_ai_location_pro: str = "global"

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

    # Raw payload storage (app.persistence.raw_payload_store) — backs
    # SOURCE_DOCUMENT.raw_payload_ref (Phase 3: "source-document storage
    # with region references"). Local-filesystem-backed for now, a
    # deliberate choice for local dev and the hackathon demo (see
    # raw_payload_store.py's module docstring for the full swap-point
    # rationale); a later phase's GCSPayloadStore reads a bucket name from
    # its own settings field instead of this one, added when that phase
    # actually needs it. Relative paths resolve against the process's
    # working directory (backend/ for `uv run uvicorn` / `uv run pytest`).
    raw_payload_storage_dir: str = "./data/raw_payloads"

    # Graph streaming (app.api.graph_router, app.graph.change_stream) —
    # PHASES.md Phase 6: GET /graph/stream's periodic SSE comment/heartbeat
    # interval, so Cloud Run (or any intermediate proxy) never times out an
    # otherwise-idle connection. Seconds.
    sse_heartbeat_interval_seconds: float = 30.0

    # OAuth ingestion connectors (Phase 14.5, ADR-022) — the consent-start
    # and callback routes (`app.api.oauth_router`) and the Gmail / Outlook
    # connectors. Client *ids* are plain config; client *secrets* are
    # themselves Secret Manager secret ids, read at startup, never in
    # `.env` in any committed form. `oauth_redirect_base_url` is the
    # public base of `gharos-api` (e.g. `https://gharos-api-xxxx.a.run.app`
    # or `http://localhost:8000` for local dev) — the callback URL is
    # `f"{oauth_redirect_base_url}/oauth/{provider}/callback"` and must be
    # registered verbatim on both providers' app registrations.
    # `frontend_connections_url` is where the callback 302s the browser
    # back to after writing (or failing to write) a connection.
    google_oauth_client_id: str = ""
    google_oauth_client_secret_ref: str = ""
    microsoft_oauth_client_id: str = ""
    microsoft_oauth_client_secret_ref: str = ""
    microsoft_oauth_tenant: str = "consumers"
    oauth_redirect_base_url: str = "http://localhost:8000"
    frontend_connections_url: str = "http://localhost:3000/connections"

    # App
    env: str = "local"
    log_level: str = "INFO"
    budget_alert_threshold_usd: float = 25.0

    @property
    def google_oauth_redirect_uri(self) -> str:
        return f"{self.oauth_redirect_base_url.rstrip('/')}/oauth/google/callback"

    @property
    def microsoft_oauth_redirect_uri(self) -> str:
        return f"{self.oauth_redirect_base_url.rstrip('/')}/oauth/microsoft/callback"

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
