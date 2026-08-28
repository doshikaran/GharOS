"""Shared fake Gemini plumbing for Phase 3 intake-agent unit tests.

Not a test module itself (no `test_*` name, never collected by pytest) —
every `test_a2_*.py` .. `test_a6_*.py` / `test_extraction_strategies.py` /
`test_golden_extraction.py` module in this package imports from here
instead of redefining `_FakeModels`/`_FakeGenaiClient` per file (mirrors
the pattern `test_gemini_client.py` established, generalised to support
queued multi-call sequences for A3/A3b/A5's two-pass tier-escalation
designs).

Extended Phase 11 (A36 Grounding/Research, `test_grounding_research_agent.py`
/ `test_simulator_pipeline.py`) with optional per-call `candidates` support,
so a call to `GeminiClient.generate_grounded_text` made through this same
fake can carry a real `google.genai.types.Candidate` tree (or none, for the
honest empty-citations path) — mirrors `test_gemini_client.py`'s own local
`_FakeResponse`/`_FakeModels`'s `candidates` field, generalised here to be
addressable per call index rather than fixed for the whole fake, since a
Simulator pipeline run makes several `generate_content` calls through one
shared queue and only specific calls among them are grounded ones.
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
    def __init__(self, text: str | None, candidates: list[Any] | None = None) -> None:
        self.text = text
        self.candidates = candidates


class FakeModels:
    """Stands in for `genai.Client.models`. Returns queued response texts
    in order across successive `generate_content` calls (falling back to
    repeating the last queued text once exhausted) — supports both
    single-call agents (A2, A4, A6) and two-pass escalating agents (A3,
    A3b, A5) from the same fake.

    `candidates_by_index` (Phase 11 addition) optionally attaches a real
    `google.genai.types.Candidate` list to one specific call, by its
    zero-based index in call order — every other call gets `candidates=None`
    (the honest "grounding did not trigger"/"not a grounded call at all"
    default). Omitted entirely, this behaves exactly as before Phase 11."""

    def __init__(
        self,
        *,
        texts: list[str],
        error: Exception | None = None,
        candidates_by_index: dict[int, list[Any]] | None = None,
    ) -> None:
        if not texts:
            raise ValueError("FakeModels requires at least one queued response text")
        self._texts = texts
        self._error = error
        self._candidates_by_index = candidates_by_index or {}
        self.calls: list[dict[str, Any]] = []

    def generate_content(self, *, model: str, contents: object, config: object = None) -> FakeResponse:
        if self._error is not None:
            raise self._error
        call_index = len(self.calls)
        self.calls.append({"model": model, "contents": contents, "config": config})
        text_index = min(call_index, len(self._texts) - 1)
        return FakeResponse(self._texts[text_index], self._candidates_by_index.get(call_index))


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
