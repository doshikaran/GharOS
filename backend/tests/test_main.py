"""Smoke tests for the FastAPI app entrypoint (`app.main`) and settings."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app
from app.settings import Settings, get_settings

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_health_config_endpoint_does_not_echo_secrets() -> None:
    response = client.get("/health/config")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"env", "gcp_region"}


def test_settings_defaults_match_env_example() -> None:
    """Field names and defaults mirror `.env.example` at the repo root —
    this test is the tripwire if the two ever drift apart. Relies on there
    being no `backend/.env` in this environment (there is none, and it is
    gitignored); a real `.env` would legitimately override these."""
    settings = Settings()
    assert settings.gcp_region == "asia-south1"
    assert settings.firestore_emulator_host == "localhost:8080"
    assert settings.firestore_database == "(default)"
    assert settings.pubsub_emulator_host == "localhost:8085"
    assert settings.pubsub_topic_prefix == "gharos-"
    assert settings.vertex_ai_location == "asia-south1"
    assert settings.env == "local"
    assert settings.log_level == "INFO"
    assert settings.budget_alert_threshold_usd == 25.0


def test_get_settings_is_cached() -> None:
    assert get_settings() is get_settings()
