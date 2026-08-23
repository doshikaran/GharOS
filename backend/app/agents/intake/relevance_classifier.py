"""A6 — Relevance Classifier (spec §15.2).

*Responsibility:* filter noise (marketing, promotional SMS) before
expensive downstream reasoning.
*Model tier:* Flash only — never escalates.
*Forbidden:* discarding anything. Low-relevance items are logged with
their verdict, never dropped from the pipeline (spec §15.2 A6's own
Failure clause: "low-relevance is logged, not deleted" — enforced here by
`RelevanceResult` always being returned to the caller, never consumed
internally).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from contracts.agents import AgentOutput, ModelTier
from contracts.graph_types import AgentId, Derivation

from ...prompts.loader import load_prompt
from ...reasoning.gemini_client import GeminiClient
from .json_utils import parse_json_response, require_float, require_str

AGENT_ID = AgentId("A6")


class RelevanceVerdict(StrEnum):
    RELEVANT = "relevant"
    LOW_RELEVANCE = "low_relevance"


@dataclass(frozen=True, slots=True)
class RelevanceClassificationResult:
    """A6's output. `verdict` is advisory triage information only —
    nothing in this codebase is permitted to use it as a reason to skip
    logging or drop an item (see module docstring)."""

    agent_output: AgentOutput
    verdict: RelevanceVerdict
    reasoning: str


class RelevanceClassifier:
    """A6 Relevance Classifier. Dependency-injected on a `GeminiClient` —
    no module-level singleton, no direct `google.genai` import."""

    def __init__(self, *, gemini_client: GeminiClient) -> None:
        self._gemini_client = gemini_client

    def classify(self, *, content: str) -> RelevanceClassificationResult:
        """Judges whether `content` is worth full downstream reasoning.

        Args:
            content: the item's text content (or a short textual
                description of a non-text item — e.g. "photographed
                document, filename: IMG_2031.jpg").

        Returns:
            A `RelevanceClassificationResult` — always returned, never
            raised on a "low relevance" verdict (that is a normal
            outcome, not a failure).

        Raises:
            ModelResponseMalformed: the model's response could not be
                parsed as the expected JSON shape.
        """
        prompt = load_prompt("A6")
        rendered = prompt.text.format(content_block=content)

        call_result = self._gemini_client.generate_structured(
            agent_id=AGENT_ID, tier=ModelTier.FLASH, prompt=rendered
        )
        parsed = parse_json_response(agent_id=AGENT_ID, text=call_result.text)

        verdict = RelevanceVerdict(require_str(parsed, "relevance", agent_id=AGENT_ID))
        reasoning = require_str(parsed, "reasoning", agent_id=AGENT_ID)
        confidence = require_float(parsed, "confidence", agent_id=AGENT_ID, default=0.5)

        agent_output = AgentOutput(
            invocation_id=uuid.uuid4().hex,
            agent_id=AGENT_ID,
            model_tier=ModelTier.FLASH,
            prompt_version=prompt.version,
            confidence=confidence,
            derivation=Derivation.EXTRACTED,
            citations=(),
            produced_at=datetime.now(UTC),
        )
        return RelevanceClassificationResult(agent_output=agent_output, verdict=verdict, reasoning=reasoning)


__all__ = ["AGENT_ID", "RelevanceClassificationResult", "RelevanceClassifier", "RelevanceVerdict"]
