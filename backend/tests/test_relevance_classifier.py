"""Tests for A6 Relevance Classifier (`app.agents.intake.relevance_classifier`).

spec §15.2 A6: Flash only, filters noise before expensive reasoning,
*never* discards — this test suite's central assertion is that a
`"low_relevance"` verdict is still a normal, fully-returned result, never
an exception or an empty/suppressed output.
"""

from __future__ import annotations

import json

from contracts.agents import ModelTier

from app.agents.intake.relevance_classifier import RelevanceClassifier, RelevanceVerdict
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _make_classifier(response_obj: dict[str, object]) -> RelevanceClassifier:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return RelevanceClassifier(gemini_client=client)


class TestRelevanceClassifier:
    def test_relevant_item_returns_relevant_verdict(self) -> None:
        classifier = _make_classifier(
            {"relevance": "relevant", "reasoning": "Contains a due date and an amount.", "confidence": 0.9}
        )
        result = classifier.classify(content="School fee due 2026-09-01, amount 5000.")

        assert result.verdict is RelevanceVerdict.RELEVANT
        assert result.agent_output.model_tier is ModelTier.FLASH
        assert result.agent_output.confidence == 0.9

    def test_low_relevance_item_is_still_returned_never_discarded(self) -> None:
        """The central forbidden-list assertion: a 'low_relevance' verdict
        is a normal return value, not a discard/exception path."""
        classifier = _make_classifier(
            {"relevance": "low_relevance", "reasoning": "Generic promotional blast.", "confidence": 0.8}
        )
        result = classifier.classify(content="50% off all school supplies this week only!!!")

        assert result.verdict is RelevanceVerdict.LOW_RELEVANCE
        # The result object itself proves nothing was dropped: the caller
        # still receives a full, populated result to log/route, exactly
        # as it would for a "relevant" verdict.
        assert result.reasoning
        assert result.agent_output.prompt_version == "v1"

    def test_uses_flash_tier_only(self) -> None:
        classifier = _make_classifier({"relevance": "relevant", "reasoning": "x", "confidence": 0.5})
        result = classifier.classify(content="anything")
        assert result.agent_output.model_tier is ModelTier.FLASH
