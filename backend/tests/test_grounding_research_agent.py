"""Tests for A36 Grounding/Research
(`app.agents.simulator.grounding_research_agent`).

Phase 11's own acceptance list, this module's share of it:
- The honest empty-citations path (ADR-017): when Google Search grounding
  does not trigger, `summary` states plainly that nothing was found —
  never backfilled with an invented source — and no Pro-tier relevance
  call is even made (nothing real to filter).
- A real citation path: citations parsed by `GeminiClient.generate_grounded_
  text` flow through unchanged onto `GroundingResult.citations`.
- Forbidden: projecting consequences. `GroundingResult.summary` is
  structurally free text (it cannot itself "carry an impact claim" any
  more precisely than any string can), so this is verified the way A36's
  own code actually enforces it: `_REJECTED_PROJECTION_PHRASES` rejects a
  fixture response whose "neutral summary" smuggles in consequence-shaped
  language, never silently stripping the offending phrase.

Unit tests only (fake Gemini, no network) — `_gemini_fakes.FakeModels`'s
Phase 11 `candidates_by_index` extension stands in for
`google.genai.types`' real grounding-chunk response tree.
"""

from __future__ import annotations

import json

import pytest
from google.genai import types

from app.agents.simulator.errors import ModelResponseMalformed
from app.agents.simulator.grounding_research_agent import AGENT_ID, GroundingResearchAgent
from app.agents.simulator.types import GroundingRequest
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(
    *, texts: list[str], candidates_by_index: dict[int, list[object]] | None = None
) -> tuple[GroundingResearchAgent, FakeModels]:
    fake_models = FakeModels(texts=texts, candidates_by_index=candidates_by_index)
    client = GeminiClient(router=fake_router(fake_models))
    return GroundingResearchAgent(gemini_client=client), fake_models


def _request(**overrides: object) -> GroundingRequest:
    defaults: dict[str, object] = {
        "branch_label": "move_to_bangalore",
        "topic": "cost of living and staff availability in Bangalore for a mid-2026 relocation",
        "household_context": "household of 4, one child in board-exam year, one elder on dialysis",
    }
    defaults.update(overrides)
    return GroundingRequest(**defaults)  # type: ignore[arg-type]


class TestHonestEmptyCitationsPath:
    def test_zero_citations_states_plainly_nothing_was_found(self) -> None:
        agent, fake_models = _agent(
            texts=[json.dumps({"search_query": "Bangalore cost of living 2026"}), "no grounded findings"]
        )

        result = agent.research(_request())

        assert result.citations == ()
        assert "no external source was found" in result.summary.lower()
        assert "not an error" in result.summary.lower()
        assert "nothing to assess freshness for" in result.freshness_note.lower()
        # Honest empty case: no Pro-tier relevance call is made at all.
        assert len(fake_models.calls) == 2

    def test_no_candidates_at_all_is_also_the_honest_empty_case(self) -> None:
        agent, fake_models = _agent(
            texts=[json.dumps({"search_query": "assisted living Mumbai 2026"}), "plain text, no grounding"]
        )

        result = agent.research(_request(branch_label="assisted_living"))

        assert result.citations == ()
        assert result.branch_label == "assisted_living"
        assert len(fake_models.calls) == 2


class TestRealCitationsFlowThroughUnchanged:
    def test_citations_from_grounding_chunks_are_carried_onto_the_result(self) -> None:
        web_chunk = types.GroundingChunk(
            web=types.GroundingChunkWeb(
                uri="https://example.com/bangalore-cost-of-living",
                title="Bangalore Cost of Living 2026",
                domain="example.com",
            )
        )
        candidate = types.Candidate(grounding_metadata=types.GroundingMetadata(grounding_chunks=[web_chunk]))
        relevance_response = json.dumps(
            {
                "summary": "Sources report rents in central Bangalore rose roughly 8% year over year.",
                "freshness_note": "Both sources were published within the last six months.",
            }
        )
        agent, fake_models = _agent(
            texts=[
                json.dumps({"search_query": "Bangalore rent trends 2026"}),
                "raw grounded findings about rent",
                relevance_response,
            ],
            candidates_by_index={1: [candidate]},
        )

        result = agent.research(_request())

        assert len(result.citations) == 1
        assert result.citations[0].uri == "https://example.com/bangalore-cost-of-living"
        assert result.citations[0].title == "Bangalore Cost of Living 2026"
        assert result.summary == ("Sources report rents in central Bangalore rose roughly 8% year over year.")
        assert len(fake_models.calls) == 3


class TestForbiddenProjectingConsequences:
    @pytest.mark.parametrize(
        "phrase",
        ["This means", "you will need", "you should", "will impact", "will cost you"],
    )
    def test_consequence_shaped_summary_is_rejected(self, phrase: str) -> None:
        web_chunk = types.GroundingChunk(
            web=types.GroundingChunkWeb(uri="https://example.com/a", title="A", domain="example.com")
        )
        candidate = types.Candidate(grounding_metadata=types.GroundingMetadata(grounding_chunks=[web_chunk]))
        relevance_response = json.dumps(
            {
                "summary": f"{phrase} relocating will disrupt the household's routine.",
                "freshness_note": "recent",
            }
        )
        agent, _fake_models = _agent(
            texts=[
                json.dumps({"search_query": "query"}),
                "raw grounded text",
                relevance_response,
            ],
            candidates_by_index={1: [candidate]},
        )

        with pytest.raises(ModelResponseMalformed) as exc_info:
            agent.research(_request())

        assert "forbidden from projecting consequences" in str(exc_info.value)

    def test_rejected_response_is_never_silently_stripped(self) -> None:
        """A hit on the keyword backstop rejects the *whole* response —
        it must never fall back to a truncated or edited summary."""
        web_chunk = types.GroundingChunk(
            web=types.GroundingChunkWeb(uri="https://example.com/a", title="A", domain="example.com")
        )
        candidate = types.Candidate(grounding_metadata=types.GroundingMetadata(grounding_chunks=[web_chunk]))
        relevance_response = json.dumps(
            {"summary": "You should expect higher fees.", "freshness_note": "recent"}
        )
        agent, _fake_models = _agent(
            texts=[json.dumps({"search_query": "query"}), "raw", relevance_response],
            candidates_by_index={1: [candidate]},
        )

        with pytest.raises(ModelResponseMalformed):
            agent.research(_request())


class TestSearchQueryValidation:
    def test_blank_search_query_is_rejected(self) -> None:
        agent, _fake_models = _agent(texts=[json.dumps({"search_query": "   "})])

        with pytest.raises(ModelResponseMalformed):
            agent.research(_request())


def test_agent_id_is_a36() -> None:
    assert str(AGENT_ID) == "A36"
