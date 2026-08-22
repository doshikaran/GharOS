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

    # Vertex AI / Gemini
    vertex_ai_location: str = "asia-south1"
    gemini_model_flash: str = "gemini-flash-latest"
    gemini_model_pro: str = "gemini-pro-latest"

    # App
    env: str = "local"
    log_level: str = "INFO"
    budget_alert_threshold_usd: float = 25.0


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Returns the process-wide cached Settings instance.

    Cached rather than a module-level singleton so tests can bypass the
    cache by constructing `Settings(...)` directly with overrides.
    """
    return Settings()
