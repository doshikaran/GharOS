"""Tests for A17 Interviewer (`app.agents.fair_allocator.interviewer_agent`).

PHASES.md Phase 8's own acceptance list, this module's share of it:
- Adaptive comparative elicitation selects an unasked, valid pair.
- A model-selected invalid pair (unknown id, identical pair, already-asked
  pair) is rejected, never silently accepted.
- Answer parsing turns real free text into a structured preference.
- Forbidden: this module never computes a valuation or an assignment, and
  has no import path to the solver at all (spec §15.8 A17).

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import ast
import inspect
import json
import types

import pytest
from contracts.graph_types import NodeId

from app.agents.fair_allocator import interviewer_agent
from app.agents.fair_allocator.errors import ModelResponseMalformed
from app.agents.fair_allocator.interviewer_agent import AGENT_ID, InterviewerAgent
from app.agents.fair_allocator.types import ComparativePreference, ComparisonQuestion, NextComparisonRequest
from app.reasoning.gemini_client import GeminiClient

from ._gemini_fakes import FakeModels, fake_router


def _agent(response_obj: dict[str, object]) -> InterviewerAgent:
    fake_models = FakeModels(texts=[json.dumps(response_obj)])
    client = GeminiClient(router=fake_router(fake_models))
    return InterviewerAgent(gemini_client=client)


def _request(
    *,
    candidate_task_ids: tuple[NodeId, ...] = (NodeId("t-1"), NodeId("t-2"), NodeId("t-3")),
    already_asked_pairs: tuple[tuple[NodeId, NodeId], ...] = (),
    preferences_so_far: tuple[ComparativePreference, ...] = (),
) -> NextComparisonRequest:
    return NextComparisonRequest(
        person_id=NodeId("person-priya"),
        candidate_task_ids=candidate_task_ids,
        task_descriptions={
            "t-1": "the two weekly school runs",
            "t-2": "calling the plumber once",
            "t-3": "grocery run",
        },
        already_asked_pairs=already_asked_pairs,
        preferences_so_far=preferences_so_far,
    )


class TestSelectNextComparison:
    def test_selects_a_valid_unasked_pair(self) -> None:
        agent = _agent(
            {
                "done": False,
                "task_a_id": "t-1",
                "task_b_id": "t-2",
                "rationale": "neither task has been compared yet",
            }
        )

        question = agent.select_next_comparison(_request())

        assert question is not None
        assert question.task_a_id == NodeId("t-1")
        assert question.task_b_id == NodeId("t-2")
        assert question.task_a_description == "the two weekly school runs"
        assert question.rationale == "neither task has been compared yet"

    def test_done_returns_none(self) -> None:
        agent = _agent({"done": True, "task_a_id": None, "task_b_id": None, "rationale": "fully explored"})

        question = agent.select_next_comparison(_request())

        assert question is None

    def test_unknown_task_id_rejected(self) -> None:
        agent = _agent(
            {"done": False, "task_a_id": "t-1", "task_b_id": "t-ghost", "rationale": "n/a"}
        )

        with pytest.raises(ModelResponseMalformed):
            agent.select_next_comparison(_request())

    def test_identical_task_ids_rejected(self) -> None:
        agent = _agent({"done": False, "task_a_id": "t-1", "task_b_id": "t-1", "rationale": "n/a"})

        with pytest.raises(ModelResponseMalformed):
            agent.select_next_comparison(_request())

    def test_already_asked_pair_rejected_regardless_of_order(self) -> None:
        agent = _agent({"done": False, "task_a_id": "t-2", "task_b_id": "t-1", "rationale": "n/a"})
        request = _request(already_asked_pairs=((NodeId("t-1"), NodeId("t-2")),))

        with pytest.raises(ModelResponseMalformed):
            agent.select_next_comparison(request)


class TestPhraseQuestion:
    def test_deterministic_no_model_call(self) -> None:
        """`phrase_question` is plain templating — spec §8.3.1's own
        worked example is exactly this shape — so it must make no Gemini
        call at all."""
        fake_models = FakeModels(texts=["should never be read"])
        agent = InterviewerAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))
        question = ComparisonQuestion(
            person_id=NodeId("person-priya"),
            task_a_id=NodeId("t-1"),
            task_a_description="two school runs",
            task_b_id=NodeId("t-2"),
            task_b_description="handle the plumber once",
            rationale="n/a",
        )

        phrased = agent.phrase_question(question)

        assert phrased == "Would you rather: (a) two school runs, or (b) handle the plumber once?"
        assert len(fake_models.calls) == 0


class TestRecordAnswer:
    _QUESTION = ComparisonQuestion(
        person_id=NodeId("person-priya"),
        task_a_id=NodeId("t-1"),
        task_a_description="two school runs",
        task_b_id=NodeId("t-2"),
        task_b_description="handle the plumber once",
        rationale="n/a",
    )

    def test_clear_preference_for_task_a(self) -> None:
        agent = _agent(
            {"preferred": "task_a", "confidence": 0.9, "reasoning": "explicitly said school runs are fine"}
        )

        preference = agent.record_answer(question=self._QUESTION, raw_answer_text="I'd rather do the runs")

        assert preference.preferred == "task_a"
        assert preference.person_id == NodeId("person-priya")
        assert preference.raw_answer_text == "I'd rather do the runs"
        assert preference.confidence == 0.9

    def test_tie_recorded(self) -> None:
        agent = _agent({"preferred": "tie", "confidence": 0.6, "reasoning": "said either is fine"})

        preference = agent.record_answer(question=self._QUESTION, raw_answer_text="either is fine honestly")

        assert preference.preferred == "tie"

    def test_unrecognised_preference_raises(self) -> None:
        agent = _agent({"preferred": "task_c", "confidence": 0.5, "reasoning": "n/a"})

        with pytest.raises(ModelResponseMalformed):
            agent.record_answer(question=self._QUESTION, raw_answer_text="whatever")

    def test_never_discards_the_original_answer_text(self) -> None:
        """The real, unmodified answer text is always retained on the
        output — never summarised away."""
        agent = _agent({"preferred": "task_b", "confidence": 0.8, "reasoning": "n/a"})
        raw = "ugh, please NOT the school runs again, I'll take the plumber call"

        preference = agent.record_answer(question=self._QUESTION, raw_answer_text=raw)

        assert preference.raw_answer_text == raw


def _references_fair_allocation_solver(module: types.ModuleType) -> bool:
    """AST-based, not a raw text search — a raw substring search over
    `inspect.getsource` would false-positive on this module's own
    docstrings (which *name* the solver to explain that they don't import
    it). Walks real `import`/`from ... import` statements only."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "fair_allocation" in node.module:
            return True
        if isinstance(node, ast.Import) and any("fair_allocation" in alias.name for alias in node.names):
            return True
    return False


class TestForbiddenBehaviour:
    """spec §15.8 A17 forbidden list: 'computing valuations or assigning.'
    Structural proof, not just a docstring claim."""

    def test_module_has_no_import_of_the_solver(self) -> None:
        assert not _references_fair_allocation_solver(interviewer_agent)

    def test_comparative_preference_has_no_cost_or_assignment_field(self) -> None:
        field_names = {f.name for f in ComparativePreference.__dataclass_fields__.values()}
        assert "cost" not in field_names
        assert "assigned_to" not in field_names
        assert "owned_by" not in field_names


def test_agent_id_is_a17() -> None:
    assert str(AGENT_ID) == "A17"
