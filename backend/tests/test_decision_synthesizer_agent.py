"""Tests for A40 Decision Synthesizer (`app.agents.simulator.decision_
synthesizer_agent`).

`TestNoVerdictField` is the structural proof this module's own docstring
names (`decision_framing_agent.py`'s neighbour, and this module's own
docstring, both point here): `DecisionBrief`/`BackwardModeAnalysis` cannot
carry a verdict because no such field exists at all, checked directly
against `dataclasses.fields()` rather than merely by convention.

Also covers:
- The `_VERDICT_PHRASES`/`VerdictLeaked` keyword-backstop rejection path —
  a fixture response containing a verdict phrase must raise, never be
  silently stripped.
- `answer_followup` grounded only in the brief's own content: proven by
  construction — every `generate_content` call, grounded or not, passes
  through the one shared fake queue, so asserting exactly one call was
  made proves no second (grounding-shaped) call could have happened.
- `synthesize_backward`'s `assumed_failure_point` citing real `supporting_
  outcome_ids` drawn from the ranked outcomes it was actually given, never
  a generic/unsupported claim.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    AgentId,
    Branch,
    Decision,
    DecisionStatus,
    Derivation,
    NodeId,
    Outcome,
    Provenance,
)

from app.agents.simulator.decision_synthesizer_agent import AGENT_ID, DecisionSynthesizerAgent
from app.agents.simulator.errors import ModelResponseMalformed, VerdictLeaked
from app.agents.simulator.types import (
    BackwardModeAnalysis,
    BackwardSynthesisRequest,
    CalibrationNarration,
    DecisionBrief,
    DecisionFrame,
)
from app.reasoning.gemini_client import GeminiClient
from app.solvers.calibration_stats import CalibrationEstimate, RankedOutcome

from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _provenance(agent: str) -> Provenance:
    return Provenance(
        derivation=Derivation.AMBIGUOUS,
        source_ref=None,
        confidence=1.0,
        deriving_agent=AgentId(agent),
        created_at=_NOW,
    )


def _decision() -> Decision:
    return Decision(
        id=NodeId("decision-1"),
        provenance=_provenance("A35"),
        question="Should the household relocate to Bangalore or remain in Mumbai?",
        trigger="Raj's company offered a relocation package",
        status=DecisionStatus.OPEN,
        resolution_summary=None,
        rationale=None,
    )


def _branch(label: str) -> Branch:
    return Branch(
        id=NodeId(f"branch-{label}"),
        provenance=_provenance("A37"),
        decision_id=NodeId("decision-1"),
        label=label,
        projected_impacts={"cost": f"{label} projected cost impact"},
        grounding_refs=(),
        critiques=(f"[A38] {label} critique on file",),
    )


def _agent(texts: list[str]) -> tuple[DecisionSynthesizerAgent, FakeModels]:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    return DecisionSynthesizerAgent(gemini_client=client), fake_models


class TestNoVerdictField:
    """Structural proof — `test_decision_synthesizer_agent.py::
    TestNoVerdictField`, named by this package's own docstrings."""

    @pytest.mark.parametrize("dataclass_type", [DecisionBrief, BackwardModeAnalysis])
    def test_no_field_names_a_verdict_recommendation_or_choice(self, dataclass_type: type) -> None:
        field_names = [f.name.lower() for f in dataclasses.fields(dataclass_type)]
        forbidden_substrings = ("recommend", "verdict", "choice", "chosen", "winner", "best_branch")
        for name in field_names:
            for forbidden in forbidden_substrings:
                assert forbidden not in name, f"{dataclass_type.__name__}.{name} smuggles a verdict field"


class TestSynthesizeHappyPath:
    def test_brief_contains_one_summary_per_real_branch_label(self) -> None:
        response = json.dumps(
            {
                "branch_summaries": {
                    "stay_in_mumbai": "Keeps the household near existing elder care and schools.",
                    "move_to_bangalore": "Higher relocation cost but closer to Raj's new role.",
                },
                "trade_offs": ["Proximity to elder care versus proximity to the new job."],
                "open_questions": ["Would the daughter's school accept a mid-year transfer?"],
            }
        )
        agent, _fake_models = _agent([response])
        branches = (_branch("stay_in_mumbai"), _branch("move_to_bangalore"))

        brief = agent.synthesize(decision=_decision(), branches=branches)

        assert brief.decision_id == NodeId("decision-1")
        assert len(brief.branch_summaries) == 2
        assert any("stay_in_mumbai" in s for s in brief.branch_summaries)
        assert any("move_to_bangalore" in s for s in brief.branch_summaries)
        assert brief.trade_offs == ("Proximity to elder care versus proximity to the new job.",)

    def test_empty_branches_raises_value_error(self) -> None:
        agent, _fake_models = _agent(["{}"])

        with pytest.raises(ValueError, match="no branches on file"):
            agent.synthesize(decision=_decision(), branches=())

    def test_mismatched_summary_keys_are_rejected(self) -> None:
        response = json.dumps(
            {
                "branch_summaries": {"wrong_label": "summary"},
                "trade_offs": [],
                "open_questions": [],
            }
        )
        agent, _fake_models = _agent([response])

        with pytest.raises(ModelResponseMalformed):
            agent.synthesize(decision=_decision(), branches=(_branch("stay_in_mumbai"),))


class TestVerdictLeakedBackstop:
    def test_verdict_phrase_in_trade_offs_raises_and_is_never_stripped(self) -> None:
        response = json.dumps(
            {
                "branch_summaries": {"stay_in_mumbai": "summary"},
                "trade_offs": ["We recommend staying in Mumbai given the elder-care schedule."],
                "open_questions": [],
            }
        )
        agent, _fake_models = _agent([response])

        with pytest.raises(VerdictLeaked) as exc_info:
            agent.synthesize(decision=_decision(), branches=(_branch("stay_in_mumbai"),))

        assert exc_info.value.field == "trade_offs"

    def test_verdict_phrase_in_followup_answer_raises(self) -> None:
        response = json.dumps({"answer": "You should choose the Bangalore branch."})
        agent, _fake_models = _agent([response])
        brief = DecisionBrief(
            decision_id=NodeId("decision-1"),
            branch_summaries=("stay_in_mumbai: summary",),
            trade_offs=("a trade-off",),
            open_questions=(),
        )

        with pytest.raises(VerdictLeaked):
            agent.answer_followup(brief, "Which one should we pick?")


class TestAnswerFollowupGroundedOnlyInTheBrief:
    def test_exactly_one_call_is_made_proving_no_grounding_call_happened(self) -> None:
        response = json.dumps(
            {"answer": "The trade-off on file is proximity to elder care versus the new job."}
        )
        agent, fake_models = _agent([response])
        brief = DecisionBrief(
            decision_id=NodeId("decision-1"),
            branch_summaries=("stay_in_mumbai: keeps elder care nearby",),
            trade_offs=("Proximity to elder care versus proximity to the new job.",),
            open_questions=("Would the school accept a mid-year transfer?",),
        )

        answer = agent.answer_followup(brief, "What's the main trade-off again?")

        assert answer == "The trade-off on file is proximity to elder care versus the new job."
        # Every Gemini network call, grounded or not, funnels through this
        # one shared fake queue — a second (grounding-shaped) call would
        # show up here. Exactly one call proves none happened.
        assert len(fake_models.calls) == 1
        sent_prompt = str(fake_models.calls[0]["contents"])
        assert "Proximity to elder care" in sent_prompt
        assert "mid-year transfer" in sent_prompt

    def test_blank_answer_is_rejected(self) -> None:
        agent, _fake_models = _agent([json.dumps({"answer": "   "})])
        brief = DecisionBrief(
            decision_id=NodeId("decision-1"), branch_summaries=(), trade_offs=(), open_questions=()
        )

        with pytest.raises(ModelResponseMalformed):
            agent.answer_followup(brief, "question")


def _calibration(*, ranked_outcomes: tuple[RankedOutcome, ...], sample_size: int) -> CalibrationNarration:
    note = (
        f"based on {sample_size} past outcomes tagged 'relocation'" if sample_size else "no past outcomes"
    )
    estimate = CalibrationEstimate(
        tag="relocation",
        sample_size=sample_size,
        mean_variance=4.0 if sample_size >= 3 else None,
        stdev_variance=2.0 if sample_size >= 3 else None,
        is_thin_history=sample_size < 3,
        note=note,
    )
    return CalibrationNarration(
        tag="relocation",
        estimate=estimate,
        ranked_outcomes=ranked_outcomes,
        narrative="Past relocations here have historically run long.",
        model_tier="pro" if sample_size else "deterministic",
    )


def _ranked_outcome(node_id: str, *, variance: float) -> RankedOutcome:
    outcome = Outcome(
        id=NodeId(node_id),
        provenance=_provenance("A26"),
        predicted="predicted",
        actual="actual",
        variance=variance,
        attribution_tags=("relocation",),
    )
    return RankedOutcome(outcome=outcome, abs_variance=abs(variance))


class TestSynthesizeBackwardCitesRealOutcomes:
    def test_supporting_outcome_ids_are_real_ranked_outcome_ids(self) -> None:
        ranked = (_ranked_outcome("outcome-1", variance=-9.0), _ranked_outcome("outcome-2", variance=3.0))
        calibration = _calibration(ranked_outcomes=ranked, sample_size=3)
        frame = DecisionFrame(
            decision_id=NodeId("decision-1"),
            question="Assume this plan failed — why? Plan: relocated in June",
            trigger="backward-mode analysis requested for category 'relocation'",
            is_false_binary=False,
            unconsidered_options=(),
            proposed_branch_labels=(),
        )
        response = json.dumps(
            {
                "assumed_failure_point": (
                    "The relocation likely slipped because past relocations here ran far longer "
                    "than planned (outcome-1 alone ran 9 units over)."
                ),
                "supporting_outcome_ids": ["outcome-1"],
                "suggested_mitigations": ["Build a longer buffer into the relocation timeline."],
            }
        )
        agent, _fake_models = _agent([response])
        request = BackwardSynthesisRequest(
            frame=frame, calibration=calibration, plan_description="relocated in June"
        )

        analysis = agent.synthesize_backward(request)

        assert analysis.supporting_outcome_ids == (NodeId("outcome-1"),)
        assert analysis.plan_description == "relocated in June"
        assert analysis.confidence_note == calibration.narrative

    def test_unreal_supporting_outcome_id_is_rejected(self) -> None:
        ranked = (_ranked_outcome("outcome-1", variance=-9.0),)
        calibration = _calibration(ranked_outcomes=ranked, sample_size=3)
        frame = DecisionFrame(
            decision_id=NodeId("decision-1"),
            question="q",
            trigger="t",
            is_false_binary=False,
            unconsidered_options=(),
            proposed_branch_labels=(),
        )
        response = json.dumps(
            {
                "assumed_failure_point": "failure point",
                "supporting_outcome_ids": ["outcome-invented"],
                "suggested_mitigations": [],
            }
        )
        agent, _fake_models = _agent([response])
        request = BackwardSynthesisRequest(frame=frame, calibration=calibration, plan_description="plan")

        with pytest.raises(ModelResponseMalformed, match="not a real ranked outcome id"):
            agent.synthesize_backward(request)

    def test_failure_point_with_no_supporting_ids_is_rejected_as_generic(self) -> None:
        ranked = (_ranked_outcome("outcome-1", variance=-9.0),)
        calibration = _calibration(ranked_outcomes=ranked, sample_size=3)
        frame = DecisionFrame(
            decision_id=NodeId("decision-1"),
            question="q",
            trigger="t",
            is_false_binary=False,
            unconsidered_options=(),
            proposed_branch_labels=(),
        )
        response = json.dumps(
            {
                "assumed_failure_point": "moves often slip",
                "supporting_outcome_ids": [],
                "suggested_mitigations": [],
            }
        )
        agent, _fake_models = _agent([response])
        request = BackwardSynthesisRequest(frame=frame, calibration=calibration, plan_description="plan")

        with pytest.raises(ModelResponseMalformed, match="never a generic claim"):
            agent.synthesize_backward(request)

    def test_zero_ranked_outcomes_is_deterministic_and_honest(self) -> None:
        calibration = _calibration(ranked_outcomes=(), sample_size=0)
        frame = DecisionFrame(
            decision_id=NodeId("decision-1"),
            question="q",
            trigger="t",
            is_false_binary=False,
            unconsidered_options=(),
            proposed_branch_labels=(),
        )
        agent, fake_models = _agent(["should never be read"])
        request = BackwardSynthesisRequest(frame=frame, calibration=calibration, plan_description="plan")

        analysis = agent.synthesize_backward(request)

        assert len(fake_models.calls) == 0
        assert analysis.supporting_outcome_ids == ()
        assert "not enough household history" in analysis.assumed_failure_point
        assert analysis.suggested_mitigations == ()

    def test_verdict_phrase_in_mitigations_raises(self) -> None:
        ranked = (_ranked_outcome("outcome-1", variance=-9.0),)
        calibration = _calibration(ranked_outcomes=ranked, sample_size=3)
        frame = DecisionFrame(
            decision_id=NodeId("decision-1"),
            question="q",
            trigger="t",
            is_false_binary=False,
            unconsidered_options=(),
            proposed_branch_labels=(),
        )
        response = json.dumps(
            {
                "assumed_failure_point": "failure point",
                "supporting_outcome_ids": ["outcome-1"],
                "suggested_mitigations": ["You should go with a phased relocation instead."],
            }
        )
        agent, _fake_models = _agent([response])
        request = BackwardSynthesisRequest(frame=frame, calibration=calibration, plan_description="plan")

        with pytest.raises(VerdictLeaked):
            agent.synthesize_backward(request)


def test_agent_id_is_a40() -> None:
    assert str(AGENT_ID) == "A40"
