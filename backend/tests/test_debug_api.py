"""Tests for `app.api.debug` — the Phase 2 mandatory-stack-proof
diagnostic endpoints.

Both endpoints are tested at the FastAPI layer with the underlying
Gemini/ADK calls replaced by fakes — `/debug/gemini-ping` via FastAPI's
`app.dependency_overrides` (its Gemini call is behind an injected
dependency), `/debug/adk-demo` via `monkeypatch` on the module-level
`run_stack_proof_demo` import (it is called directly, not through a
`Depends`). This proves routing, response shape, and the failure->502
mapping without any real network call. The real live proof these
endpoints wrap lives in `test_gemini_client.py`'s `live_gcp` test and the
Phase 2 report's manual verification against a locally running
`uvicorn app.main:app`.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from fastapi.testclient import TestClient

import app.api.debug as debug_module
from app.agents.errors import AgentRunIncomplete
from app.agents.orchestration.stack_proof_agent import StackProofResult
from app.main import app
from app.reasoning.errors import GeminiCallFailed
from app.reasoning.gemini_client import GeminiCallResult
from app.reasoning.model_router import ModelRouter

client = TestClient(app)


class _FakeGeminiClient:
    """Stands in for `GeminiClient` behind the `get_gemini_client`
    dependency — records every call so a test can assert the endpoint
    passed through the expected `agent_id`/`tier`/`prompt`."""

    def __init__(self, *, result: GeminiCallResult | None = None, error: Exception | None = None) -> None:
        self._result = result
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def generate_text(self, *, agent_id: AgentId, tier: ModelTier, prompt: str) -> GeminiCallResult:
        self.calls.append({"agent_id": agent_id, "tier": tier, "prompt": prompt})
        if self._error is not None:
            raise self._error
        assert self._result is not None
        return self._result


class TestGeminiPingEndpoint:
    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_returns_real_response_shape_on_success(self) -> None:
        fake_client = _FakeGeminiClient(
            result=GeminiCallResult(
                agent_id=debug_module.GEMINI_PING_AGENT_ID,
                tier=ModelTier.FLASH,
                model_name="gemini-2.5-flash",
                text="pong",
                produced_at=datetime.now(UTC),
            )
        )
        app.dependency_overrides[debug_module.get_gemini_client] = lambda: fake_client

        response = client.get("/debug/gemini-ping")

        assert response.status_code == 200
        assert response.json() == {
            "response_text": "pong",
            "model_tier": "flash",
            "model_name": "gemini-2.5-flash",
        }
        assert fake_client.calls == [
            {
                "agent_id": debug_module.GEMINI_PING_AGENT_ID,
                "tier": ModelTier.FLASH,
                "prompt": debug_module._PING_PROMPT,
            }
        ]

    def test_maps_gemini_call_failed_to_502_not_fabricated_success(self) -> None:
        error = GeminiCallFailed(
            agent_id=debug_module.GEMINI_PING_AGENT_ID, model_name="gemini-2.5-flash", reason="boom"
        )
        app.dependency_overrides[debug_module.get_gemini_client] = lambda: _FakeGeminiClient(error=error)

        response = client.get("/debug/gemini-ping")

        assert response.status_code == 502
        assert "boom" in response.json()["detail"]

    def test_get_model_router_dependency_builds_a_real_router(self) -> None:
        """`get_model_router` is exercised for real (not overridden) —
        proves the DI wiring itself, not just the fake substituted below
        it, constructs a usable `ModelRouter`."""
        from app.settings import Settings

        router = debug_module.get_model_router(Settings(gcp_project_id="p"))
        assert isinstance(router, ModelRouter)


class TestAdkDemoEndpoint:
    def teardown_method(self) -> None:
        app.dependency_overrides.clear()

    def test_returns_proof_the_tool_was_invoked(self, monkeypatch: pytest.MonkeyPatch) -> None:
        fake_result = StackProofResult(
            response_text="It is 2026-08-22T12:00:00+00:00.",
            tool_name="get_current_utc_time",
            tool_result={"utc_time": "2026-08-22T12:00:00+00:00"},
            model_name="gemini-2.5-flash",
            produced_at=datetime.now(UTC),
        )

        async def fake_run_stack_proof_demo(
            *, router: ModelRouter, project_id: str, location: str
        ) -> StackProofResult:
            return fake_result

        monkeypatch.setattr(debug_module, "run_stack_proof_demo", fake_run_stack_proof_demo)

        response = client.post("/debug/adk-demo")

        assert response.status_code == 200
        body = response.json()
        assert body["tool_invoked"] == "get_current_utc_time"
        assert body["tool_result"] == {"utc_time": "2026-08-22T12:00:00+00:00"}
        assert body["model_name"] == "gemini-2.5-flash"
        assert "2026-08-22T12:00:00" in body["response_text"]

    def test_maps_agent_run_incomplete_to_502_not_fabricated_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_run_stack_proof_demo(
            *, router: ModelRouter, project_id: str, location: str
        ) -> StackProofResult:
            raise AgentRunIncomplete(agent_id=AgentId("DEBUG-STACK-PROOF"), reason="tool never invoked")

        monkeypatch.setattr(debug_module, "run_stack_proof_demo", fake_run_stack_proof_demo)

        response = client.post("/debug/adk-demo")

        assert response.status_code == 502
        assert "tool never invoked" in response.json()["detail"]
