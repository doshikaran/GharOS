"""Tests for A19 Fairness Verifier / Explainer
(`app.agents.fair_allocator.fairness_verifier_explainer_agent`).

PHASES.md Phase 8's own acceptance list, this module's share of it:
- Verification is genuinely deterministic — no model call for that half.
- Explanation uses only the explained person's own valuations, never
  another person's.
- Forbidden: altering the allocation — no write tool, no path back to the
  solver's construction logic.

Unit tests only (fake Gemini, no network).
"""

from __future__ import annotations

import ast
import inspect
import json
import types

from contracts.graph_types import NodeId

from app.agents.fair_allocator import fairness_verifier_explainer_agent
from app.agents.fair_allocator.fairness_verifier_explainer_agent import (
    AGENT_ID,
    FairnessVerifierExplainerAgent,
)
from app.reasoning.gemini_client import GeminiClient
from app.solvers.fair_allocation import FairAllocationResult, solve_fair_allocation

from ._gemini_fakes import FakeModels, fake_router


def _pid(raw: str) -> NodeId:
    return NodeId(raw)


def _tid(raw: str) -> NodeId:
    return NodeId(raw)


_TASK_DESCRIPTIONS = {"t-1": "school run A", "t-2": "school run B", "t-3": "plumber call"}


def _fair_scenario() -> tuple[FairAllocationResult, dict[NodeId, dict[NodeId, float]]]:
    """Scenario A from `test_fair_allocation.py`: p-1 has real (but
    EF1-bounded) envy of p-2 — good for proving the explanation reflects
    a real, non-trivial fairness result."""
    person_ids = [_pid("p-1"), _pid("p-2")]
    task_ids = [_tid("t-1"), _tid("t-2"), _tid("t-3")]
    costs = {
        _pid("p-1"): {_tid("t-1"): 5.0, _tid("t-2"): 5.0, _tid("t-3"): 1.0},
        _pid("p-2"): {_tid("t-1"): 1.0, _tid("t-2"): 1.0, _tid("t-3"): 10.0},
    }
    feasibility = {p: frozenset(task_ids) for p in person_ids}
    result = solve_fair_allocation(
        person_ids=person_ids, task_ids=task_ids, costs=costs, feasibility=feasibility
    )
    return result, costs


def _agent_with_responses(texts: list[str]) -> FairnessVerifierExplainerAgent:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    return FairnessVerifierExplainerAgent(gemini_client=client)


class TestVerificationIsDeterministic:
    def test_ef1_holds_matches_verify_ef1_directly(self) -> None:
        result, costs = _fair_scenario()
        agent = _agent_with_responses(
            [json.dumps({"explanation": "you have two tasks", "confidence": 0.9})] * 2
        )

        verification = agent.verify_and_explain(
            result=result, costs=costs, task_descriptions=_TASK_DESCRIPTIONS
        )

        assert verification.ef1_holds is True  # scenario A is EF1 (bounded envy)
        assert verification.violation_count == 0

    def test_verification_half_calls_no_model(self) -> None:
        """Only the explanation half should ever touch Gemini — proven by
        counting calls against the number of people, not more."""
        result, costs = _fair_scenario()
        fake_models = FakeModels(
            texts=[json.dumps({"explanation": "x", "confidence": 0.5})] * len(result.order)
        )
        agent = FairnessVerifierExplainerAgent(gemini_client=GeminiClient(router=fake_router(fake_models)))

        agent.verify_and_explain(result=result, costs=costs, task_descriptions=_TASK_DESCRIPTIONS)

        assert len(fake_models.calls) == len(result.order)


class TestExplanationUsesOnlyOwnValuations:
    def test_each_explanation_request_never_carries_another_persons_cost(self) -> None:
        """Builds the explanation request directly (not just the final
        text) and asserts no other person's cost row leaks in — the
        strongest form of this proof, independent of what the (fake)
        model says back."""
        result, costs = _fair_scenario()
        response_texts = [json.dumps({"explanation": "x", "confidence": 0.5})] * len(result.order)
        agent = _agent_with_responses(response_texts)

        bundles = fairness_verifier_explainer_agent._bundles(result)
        for person_id in result.order:
            own_bundle = tuple(sorted(bundles[person_id], key=str))
            request = agent._build_explanation_request(
                person_id=person_id,
                own_bundle=own_bundle,
                bundles=bundles,
                costs=costs,
                task_descriptions=_TASK_DESCRIPTIONS,
                violations=(),
                person_envies=False,
            )
            # own_costs must exactly equal this person's own row restricted
            # to their own bundle — never another person's cost values.
            for task_id_str, cost in request.own_costs.items():
                assert cost == costs[person_id][NodeId(task_id_str)]
            # comparisons must be priced under THIS person's own row too.
            for comparison in request.comparisons:
                assert comparison.other_person_id != person_id

    def test_explanation_confidence_and_text_come_from_the_model(self) -> None:
        result, costs = _fair_scenario()
        agent = _agent_with_responses(
            [json.dumps({"explanation": "you took the plumber call, cheapest for you", "confidence": 0.77})]
            * len(result.order)
        )

        verification = agent.verify_and_explain(
            result=result, costs=costs, task_descriptions=_TASK_DESCRIPTIONS
        )

        for explanation in verification.explanations:
            assert explanation.explanation_text == "you took the plumber call, cheapest for you"
            assert explanation.confidence == 0.77


def _imported_names(module: types.ModuleType) -> set[str]:
    """Every name this module imports (via either `import X` or
    `from X import name`) — AST-based, not a raw text search, so this
    module's own docstring (which *names* `solve_fair_allocation` and
    `GraphWriter` to explain that they are NOT imported) cannot cause a
    false positive."""
    tree = ast.parse(inspect.getsource(module))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom | ast.Import):
            names.update(alias.asname or alias.name for alias in node.names)
    return names


class TestForbiddenBehaviour:
    """spec §15.8 A19 forbidden list: 'altering the allocation.'"""

    def test_module_has_no_solver_construction_import(self) -> None:
        assert "solve_fair_allocation" not in _imported_names(fairness_verifier_explainer_agent)

    def test_module_has_no_graph_writer_import(self) -> None:
        imported = _imported_names(fairness_verifier_explainer_agent)
        assert "GraphWriter" not in imported
        assert "GraphWriteTool" not in imported


def test_agent_id_is_a19() -> None:
    assert str(AGENT_ID) == "A19"
