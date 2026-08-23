"""Shared fake Gemini plumbing for Phase 3 intake-agent unit tests.

Not a test module itself (no `test_*` name, never collected by pytest) —
every `test_a2_*.py` .. `test_a6_*.py` / `test_extraction_strategies.py` /
`test_golden_extraction.py` module in this package imports from here
instead of redefining `_FakeModels`/`_FakeGenaiClient` per file (mirrors
the pattern `test_gemini_client.py` established, generalised to support
queued multi-call sequences for A3/A3b/A5's two-pass tier-escalation
designs).
"""

from __future__ import annotations

from typing import Any, cast

from google import genai

from app.reasoning.model_router import ModelRouter

_PROJECT_ID = "gharos-test-project"
_LOCATION = "asia-south1"
_MODEL_FLASH = "gemini-2.5-flash"
_MODEL_PRO = "gemini-2.5-pro"


class FakeResponse:
    def __init__(self, text: str | None) -> None:
        self.text = text


class FakeModels:
    """Stands in for `genai.Client.models`. Returns queued response texts
    in order across successive `generate_content` calls (falling back to
    repeating the last queued text once exhausted) — supports both
    single-call agents (A2, A4, A6) and two-pass escalating agents (A3,
    A3b, A5) from the same fake."""

    def __init__(self, *, texts: list[str], error: Exception | None = None) -> None:
        if not texts:
            raise ValueError("FakeModels requires at least one queued response text")
        self._texts = texts
        self._error = error
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: object, config: object = None) -> FakeResponse:
        if self._error is not None:
            raise self._error
        call_index = len(self.calls)
        self.calls.append({"model": model, "contents": contents, "config": config})
        text_index = min(call_index, len(self._texts) - 1)
        return FakeResponse(self._texts[text_index])


class FakeGenaiClient:
    def __init__(self, models: FakeModels) -> None:
        self.models = models


def fake_router(fake_models: FakeModels) -> ModelRouter:
    """Builds a real `ModelRouter` wired to `fake_models` via an injected
    `client_factory` — exercises real allowlist/tier-routing logic with
    zero network access, exactly `test_gemini_client.py`'s established
    pattern."""

    def factory(project_id: str, location: str) -> genai.Client:
        return cast(genai.Client, FakeGenaiClient(fake_models))

    return ModelRouter(
        project_id=_PROJECT_ID,
        location=_LOCATION,
        model_flash=_MODEL_FLASH,
        model_pro=_MODEL_PRO,
        client_factory=factory,
    )


__all__ = ["FakeGenaiClient", "FakeModels", "FakeResponse", "fake_router"]
