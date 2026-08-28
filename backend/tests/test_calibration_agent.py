"""Tests for A39 Calibration (`app.agents.simulator.calibration_agent`).

Phase 11's own acceptance list, this module's share of it:
- Zero-history case: no model call at all, `narrative == estimate.note`
  verbatim, `model_tier == "deterministic"`.
- Thin-history case (1 <= sample_size < 3): a real model call narrates,
  but `estimate.note` is guaranteed to appear verbatim in the returned
  narrative regardless of what the model produced.
- A real N>=3 case: `estimate`/`ranked_outcomes` are exactly what
  `app.solvers.calibration_stats` independently computes over the same
  real `Outcome`s — this agent never recomputes or overrides a statistic
  itself.

Unit tests only (fake Gemini, no network; `FakeGraphReader` test double).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime

from contracts.graph_types import AgentId, Derivation, NodeId, Outcome, Provenance

from app.agents.simulator.calibration_agent import AGENT_ID, CalibrationAgent
from app.reasoning.gemini_client import GeminiClient
from app.solvers.calibration_stats import compute_calibration, rank_by_absolute_variance

from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _outcome(node_id: str, *, predicted: str, actual: str, variance: float | None, tag: str) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=Provenance(
            # AMBIGUOUS/no source_ref — only EXTRACTED/INFERRED provenance
            # requires a real SourceRef (contracts.graph_types.Provenance).
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=0.8,
            deriving_agent=AgentId("A26"),
            created_at=_NOW,
        ),
        predicted=predicted,
        actual=actual,
        variance=variance,
        attribution_tags=(tag,),
    )


def _agent(*, texts: list[str], outcomes_by_tag: dict[str, tuple[Outcome, ...]]) -> tuple[
    CalibrationAgent, FakeModels
]:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    reader = FakeGraphReader(outcome_variance_by_tag=outcomes_by_tag)
    return CalibrationAgent(gemini_client=client, graph_reader=reader), fake_models


class TestZeroHistoryIsDeterministic:
    def test_no_model_call_and_narrative_is_the_note_verbatim(self) -> None:
        agent, fake_models = _agent(texts=["should never be read"], outcomes_by_tag={})

        narration = agent.narrate("relocation")

        assert len(fake_models.calls) == 0
        assert narration.model_tier == "deterministic"
        assert narration.estimate.sample_size == 0
        assert narration.estimate.is_thin_history is True
        assert narration.narrative == narration.estimate.note
        assert "no past outcomes" in narration.narrative.lower()


class TestThinHistoryNeverFabricatesConfidence:
    def test_note_appears_verbatim_even_when_model_omits_it(self) -> None:
        outcomes = (
            _outcome(
                "outcome-1",
                predicted="relocation completes in 6 weeks",
                actual="relocation took 11 weeks",
                variance=5.0,
                tag="relocation",
            ),
        )
        # The scripted model narrative deliberately omits the exact note text.
        scripted_narrative = "Only one past relocation is on file; it took much longer than planned."
        agent, fake_models = _agent(
            texts=[json.dumps({"narrative": scripted_narrative})],
            outcomes_by_tag={"relocation": outcomes},
        )

        narration = agent.narrate("relocation")

        assert len(fake_models.calls) == 1
        assert narration.model_tier == "pro"
        assert narration.estimate.is_thin_history is True
        assert narration.estimate.mean_variance is None
        assert narration.estimate.stdev_variance is None
        assert scripted_narrative in narration.narrative
        assert narration.estimate.note in narration.narrative

    def test_note_not_duplicated_when_model_already_included_it(self) -> None:
        outcomes = (
            _outcome(
                "outcome-1",
                predicted="p",
                actual="a",
                variance=2.0,
                tag="staff_transition",
            ),
        )
        estimate = compute_calibration("staff_transition", outcomes)
        scripted_narrative = f"Here is the honest picture: {estimate.note}"
        agent, _fake_models = _agent(
            texts=[json.dumps({"narrative": scripted_narrative})],
            outcomes_by_tag={"staff_transition": outcomes},
        )

        narration = agent.narrate("staff_transition")

        assert narration.narrative == scripted_narrative
        assert narration.narrative.count(estimate.note) == 1


class TestRealSampleNeverRecomputedByTheAgent:
    def test_estimate_and_ranked_outcomes_match_the_tool_exactly(self) -> None:
        outcomes = (
            _outcome("outcome-1", predicted="p1", actual="a1", variance=3.0, tag="relocation"),
            _outcome("outcome-2", predicted="p2", actual="a2", variance=-7.0, tag="relocation"),
            _outcome("outcome-3", predicted="p3", actual="a3", variance=1.0, tag="relocation"),
            _outcome("outcome-unsettled", predicted="p4", actual="a4", variance=None, tag="relocation"),
        )
        agent, fake_models = _agent(
            texts=[json.dumps({"narrative": "Relocations here have historically run over."})],
            outcomes_by_tag={"relocation": outcomes},
        )

        narration = agent.narrate("relocation")

        expected_estimate = compute_calibration("relocation", outcomes)
        expected_ranked = rank_by_absolute_variance(outcomes, top_n=3)

        assert narration.estimate == expected_estimate
        assert narration.ranked_outcomes == expected_ranked
        assert narration.estimate.is_thin_history is False
        assert narration.estimate.sample_size == 3
        assert narration.model_tier == "pro"
        assert len(fake_models.calls) == 1
        # The numbers the model was actually shown are the tool's own real
        # numbers — never something this agent invented independently.
        rendered_prompt = str(fake_models.calls[0]["contents"])
        assert "outcome-2" in rendered_prompt
        assert "-7" in rendered_prompt


def test_agent_id_is_a39() -> None:
    assert str(AGENT_ID) == "A39"
