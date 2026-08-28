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
2. **Live integration tests**, marked `live_gcp` and skipped by
   default — make real calls to the real `blissful-trail-506312-t0`
   project via real ADC credentials. Enable with:

       GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=blissful-trail-506312-t0 \\
           uv run pytest tests/test_gemini_client.py -m live_gcp

   Off by default so the rest of the suite never needs live credentials
   or makes a real network call.

`TestGenerateGroundedText*` (ADR-017, Phase 11 A36) covers
`generate_grounded_text`/`GroundedCitation`/`GroundedGeminiCallResult`:
unit tests against a fake `Candidate`/`GroundingMetadata` response tree
for the honest-empty-citations path, plus one live test
(`test_real_grounded_call_against_live_search`) proving a real
Google-Search-grounded call against a genuinely time-sensitive query
returns at least one citation with a real, well-formed URI — run
personally by the CTO as part of Gate 11 verification (ADR-017).
"""

from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import Any, cast

import pytest
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from app.reasoning.errors import GeminiCallFailed, ProTierNotAllowlisted
from app.reasoning.gemini_client import (
    GeminiCallResult,
    GeminiClient,
    GroundedCitation,
    GroundedGeminiCallResult,
)
from app.reasoning.model_router import ModelRouter
from app.settings import Settings

_PROJECT_ID = "gharos-test-project"
_LOCATION = "asia-south1"
_MODEL_FLASH = "gemini-2.5-flash"
_MODEL_PRO = "gemini-2.5-pro"


class _FakeResponse:
    def __init__(self, text: str | None, candidates: list[Any] | None = None) -> None:
        self.text = text
        self.candidates = candidates


class _FakeModels:
    """Stands in for `genai.Client.models` — records every call it
    receives so a test can assert the resolved model name was actually
    used, without any real network access."""

    def __init__(
        self,
        *,
        text: str | None = None,
        error: Exception | None = None,
        candidates: list[Any] | None = None,
    ) -> None:
        self._text = text
        self._error = error
        self._candidates = candidates
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: str, config: object = None) -> _FakeResponse:
        self.calls.append({"model": model, "contents": contents, "config": config})
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._text, self._candidates)


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
        assert fake_models.calls == [{"model": _MODEL_FLASH, "contents": "ping", "config": None}]

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


class TestElevatedThinkingBudget:
    """`thinking_budget` is opt-in per call (PHASES.md §2.1 rule 4:
    "elevated thinking budgets are opt-in per agent, never global") —
    `None` (the default, every pre-existing caller) must leave the built
    `GenerateContentConfig` byte-for-byte as it already was; a caller that
    passes a value gets a real `types.ThinkingConfig` attached."""

    def test_no_thinking_budget_omits_thinking_config(self) -> None:
        fake_models = _FakeModels(text='{"ok": true}')
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        client.generate_structured(agent_id=AgentId("A2"), tier=ModelTier.FLASH, prompt="x")

        config = fake_models.calls[0]["config"]
        assert config is not None
        assert config.thinking_config is None
        assert config.response_mime_type == "application/json"

    def test_thinking_budget_attaches_thinking_config(self) -> None:
        fake_models = _FakeModels(text='{"ok": true}')
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        client.generate_structured(
            agent_id=AgentId("A12"), tier=ModelTier.PRO, prompt="implicate", thinking_budget=16000
        )

        config = fake_models.calls[0]["config"]
        assert config is not None
        assert config.thinking_config is not None
        assert config.thinking_config.thinking_budget == 16000
        assert config.response_mime_type == "application/json"


class TestGenerateGroundedText:
    """`GeminiClient.generate_grounded_text` (ADR-017, Phase 11 A36) —
    unit tests against a fake SDK response tree. Confirmed shape (see
    `app.reasoning.gemini_client._extract_grounding_citations`'s
    docstring): `response.candidates[0].grounding_metadata.
    grounding_chunks[i].web.{uri,title,domain}` — the fakes below mirror
    that exact real shape rather than a guessed one."""

    def test_no_response_mime_type_ever_set_on_grounded_call(self) -> None:
        """The mutually-exclusive-with-Search-tool constraint (confirmed
        against a real live call — see the module and method docstrings)
        means this call must never attach `response_mime_type`."""
        fake_models = _FakeModels(text="grounded answer", candidates=None)
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

        config = fake_models.calls[0]["config"]
        assert config is not None
        assert config.response_mime_type is None
        assert config.tools is not None and len(config.tools) == 1
        assert config.tools[0].google_search is not None

    def test_grounding_triggered_parses_real_shape_into_citations(self) -> None:
        web_chunk = types.GroundingChunk(
            web=types.GroundingChunkWeb(uri="https://example.com/a", title="Example A", domain="example.com")
        )
        candidate = types.Candidate(
            grounding_metadata=types.GroundingMetadata(grounding_chunks=[web_chunk])
        )
        fake_models = _FakeModels(text="grounded answer", candidates=[candidate])
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

        assert isinstance(result, GroundedGeminiCallResult)
        assert result.text == "grounded answer"
        assert len(result.citations) == 1
        citation = result.citations[0]
        assert isinstance(citation, GroundedCitation)
        assert citation.uri == "https://example.com/a"
        assert citation.title == "Example A"
        # retrieved_at is real UTC "now" at call time, not derived from the
        # (fake) response at all.
        assert citation.retrieved_at.tzinfo is not None
        assert (datetime.now(UTC) - citation.retrieved_at).total_seconds() < 5

    def test_grounding_chunk_title_falls_back_to_domain_then_uri(self) -> None:
        no_title_chunk = types.GroundingChunk(
            web=types.GroundingChunkWeb(uri="https://example.com/b", title=None, domain="example.com")
        )
        no_title_or_domain_chunk = types.GroundingChunk(
            web=types.GroundingChunkWeb(uri="https://example.com/c", title=None, domain=None)
        )
        candidate = types.Candidate(
            grounding_metadata=types.GroundingMetadata(
                grounding_chunks=[no_title_chunk, no_title_or_domain_chunk]
            )
        )
        fake_models = _FakeModels(text="grounded answer", candidates=[candidate])
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

        assert result.citations[0].title == "example.com"
        assert result.citations[1].title == "https://example.com/c"

    def test_grounding_not_triggered_returns_empty_citations_never_fabricated(self) -> None:
        """Honest empty case (ADR-017): no `grounding_metadata` at all —
        a real, expected outcome, never backfilled with an invented
        citation."""
        candidate = types.Candidate(grounding_metadata=None)
        fake_models = _FakeModels(text="a plain, ungrounded answer", candidates=[candidate])
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

        assert result.citations == ()
        assert result.text == "a plain, ungrounded answer"

    def test_no_candidates_at_all_returns_empty_citations(self) -> None:
        fake_models = _FakeModels(text="a plain, ungrounded answer", candidates=None)
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

        assert result.citations == ()

    def test_chunk_with_no_web_or_blank_uri_contributes_no_citation(self) -> None:
        no_web_chunk = types.GroundingChunk(web=None)
        blank_uri_chunk = types.GroundingChunk(web=types.GroundingChunkWeb(uri="", title="Blank"))
        candidate = types.Candidate(
            grounding_metadata=types.GroundingMetadata(grounding_chunks=[no_web_chunk, blank_uri_chunk])
        )
        fake_models = _FakeModels(text="answer", candidates=[candidate])
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        result = client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

        assert result.citations == ()

    def test_api_error_raises_gemini_call_failed(self) -> None:
        api_error = genai_errors.APIError(500, {"error": {"message": "quota exceeded"}})
        fake_models = _FakeModels(error=api_error)
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        with pytest.raises(GeminiCallFailed):
            client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

    def test_empty_response_raises_gemini_call_failed(self) -> None:
        fake_models = _FakeModels(text=None)
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        with pytest.raises(GeminiCallFailed):
            client.generate_grounded_text(agent_id=AgentId("A36"), tier=ModelTier.FLASH, prompt="ping")

    def test_pro_tier_from_non_allowlisted_agent_propagates_allowlist_error(self) -> None:
        fake_models = _FakeModels(text="should never be reached")
        router = _router_with_fake_client(fake_models)
        client = GeminiClient(router=router)

        with pytest.raises(ProTierNotAllowlisted):
            client.generate_grounded_text(agent_id=AgentId("A99"), tier=ModelTier.PRO, prompt="ping")

        assert fake_models.calls == []


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


@pytest.mark.live_gcp
@pytest.mark.skipif(
    not _LIVE_TESTS_ENABLED or not _LIVE_PROJECT_ID,
    reason=(
        "live GCP test — set GHAROS_RUN_LIVE_GCP_TESTS=1 and GCP_PROJECT_ID "
        "to run a real Google-Search-grounded call against Vertex AI"
    ),
)
def test_real_grounded_call_against_live_search() -> None:
    """ADR-017 / Gate 11's own load-bearing live proof, run personally by
    the CTO as part of Gate 11 verification: a real `generate_grounded_text`
    call, real ADC credentials, a real network call, against a genuinely
    time-sensitive query that should trigger real Google Search grounding
    — proves at least one real citation with a real, well-formed URI comes
    back, not a mocked or invented one."""
    settings = Settings(gcp_project_id=_LIVE_PROJECT_ID)
    router = ModelRouter(
        project_id=settings.gcp_project_id,
        location=settings.vertex_ai_location,
        model_flash=settings.gemini_model_flash,
        model_pro=settings.gemini_model_pro,
    )
    client = GeminiClient(router=router)

    result = client.generate_grounded_text(
        agent_id=AgentId("A36"),
        tier=ModelTier.FLASH,
        prompt=(
            "What is today's date, and what is one real current news "
            "headline from India today? Cite your source."
        ),
    )

    assert result.text  # a real model response came back
    assert len(result.citations) >= 1, "expected real Search grounding for a time-sensitive query"
    for citation in result.citations:
        assert citation.uri.startswith("http"), f"citation URI is not well-formed: {citation.uri!r}"
        assert citation.title
        assert citation.retrieved_at.tzinfo is not None
