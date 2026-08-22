"""Tests for `app.reasoning.gemini_client` — the single-turn Vertex AI
Gemini call wrapper built on `ModelRouter`.

Two tiers, matching this repo's established convention
(`test_secret_manager_adapter.py`):

1. **Unit tests** (always run) — a fake `google.genai.Client` double
   (`_FakeGenaiClient`) implementing only `.models.generate_content(...)`,
   proving `GeminiClient`'s own logic: successful text extraction, a
   failed SDK call raising `GeminiCallFailed`, an empty response raising
   `GeminiCallFailed`, and that `ModelRouter`'s allowlist/tier errors
   propagate unchanged through `generate_text`.
2. **One live integration test**, marked `live_gcp` and skipped by
   default — makes a real Flash-tier call to the real
   `blissful-trail-506312-t0` project via real ADC credentials. Enable
   with:

       GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=blissful-trail-506312-t0 \\
           uv run pytest tests/test_gemini_client.py -m live_gcp

   Off by default so the rest of the suite never needs live credentials
   or makes a real network call.
"""

from __future__ import annotations

import os
from typing import Any, cast

import pytest
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google import genai
from google.genai import errors as genai_errors

from app.reasoning.errors import GeminiCallFailed, ProTierNotAllowlisted
from app.reasoning.gemini_client import GeminiCallResult, GeminiClient
from app.reasoning.model_router import ModelRouter
from app.settings import Settings

_PROJECT_ID = "gharos-test-project"
_LOCATION = "asia-south1"
_MODEL_FLASH = "gemini-2.5-flash"
_MODEL_PRO = "gemini-2.5-pro"


class _FakeResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text


class _FakeModels:
    """Stands in for `genai.Client.models` — records every call it
    receives so a test can assert the resolved model name was actually
    used, without any real network access."""

    def __init__(self, *, text: str | None = None, error: Exception | None = None) -> None:
        self._text = text
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: str) -> _FakeResponse:
        self.calls.append({"model": model, "contents": contents})
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._text)


class _FakeGenaiClient:
    def __init__(self, models: _FakeModels) -> None:
        self.models = models


def _router_with_fake_client(fake_models: _FakeModels) -> ModelRouter:
    def factory(project_id: str, location: str) -> genai.Client:
        return cast(genai.Client, _FakeGenaiClient(fake_models))

    return ModelRouter(
        project_id=_PROJECT_ID,
        location=_LOCATION,
        model_flash=_MODEL_FLASH,
        model_pro=_MODEL_PRO,
        client_factory=factory,
    )


class TestGenerateTextSuccess:
    def test_returns_result_with_resolved_model_and_tier(self) -> None:
        fake_models = _FakeModels(text="pong")
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_text(agent_id=AgentId("A2"), tier=ModelTier.FLASH, prompt="ping")

        assert isinstance(result, GeminiCallResult)
        assert result.text == "pong"
        assert result.model_name == _MODEL_FLASH
        assert result.tier is ModelTier.FLASH
        assert fake_models.calls == [{"model": _MODEL_FLASH, "contents": "ping"}]

    def test_pro_tier_call_from_allowlisted_agent_uses_pro_model(self) -> None:
        fake_models = _FakeModels(text="deep thoughts")
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_text(agent_id=AgentId("A12"), tier=ModelTier.PRO, prompt="implicate")

        assert result.model_name == _MODEL_PRO
        assert result.tier is ModelTier.PRO


class TestGenerateTextFailurePaths:
    def test_api_error_raises_gemini_call_failed_not_reinterpreted_as_success(self) -> None:
        api_error = genai_errors.APIError(500, {"error": {"message": "quota exceeded"}})
        fake_models = _FakeModels(error=api_error)
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        with pytest.raises(GeminiCallFailed) as exc_info:
            client.generate_text(agent_id=AgentId("A2"), tier=ModelTier.FLASH, prompt="ping")

        assert exc_info.value.agent_id == AgentId("A2")
        assert exc_info.value.model_name == _MODEL_FLASH
        assert exc_info.value.__cause__ is api_error

    def test_empty_response_raises_gemini_call_failed(self) -> None:
        fake_models = _FakeModels(text=None)
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        with pytest.raises(GeminiCallFailed):
            client.generate_text(agent_id=AgentId("A2"), tier=ModelTier.FLASH, prompt="ping")

    def test_pro_tier_from_non_allowlisted_agent_propagates_allowlist_error(self) -> None:
        """`GeminiClient` never catches or downgrades `ModelRouter`'s
        allowlist error — it propagates unchanged, so the Gate 2 tripwire
        lives in exactly one place (`test_model_router.py`)."""
        fake_models = _FakeModels(text="should never be reached")
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        with pytest.raises(ProTierNotAllowlisted):
            client.generate_text(agent_id=AgentId("A99"), tier=ModelTier.PRO, prompt="ping")

        assert fake_models.calls == []  # never reached the SDK call


_LIVE_TESTS_ENABLED = os.environ.get("GHAROS_RUN_LIVE_GCP_TESTS") == "1"
_LIVE_PROJECT_ID = os.environ.get("GCP_PROJECT_ID", "")


@pytest.mark.live_gcp
@pytest.mark.skipif(
    not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID,
    reason=(
        "live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID "
        "to run a real Flash-tier call against Vertex AI"
    ),
)
def test_real_flash_tier_call_against_live_vertex_ai() -> None:
    """Proves Gate 2 requirement 1 end to end: a real `ModelRouter`, real
    ADC credentials, a real network call to the live project, a real
    Gemini response. Not mocked."""
    settings = Settings(gcp_project_id=_LIVE_PROJECT_ID)
    router = ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )
    client = GeminiClient(router=router)

    result = client.generate_text(
        agent_id=AgentId("A2"),
        tier=ModelTier.FLASH,
        prompt="Reply with exactly the single word: pong",
    )

    assert result.text  # non-empty: a real model response came back
    assert result.model_name == settings.gemini_model_flash
