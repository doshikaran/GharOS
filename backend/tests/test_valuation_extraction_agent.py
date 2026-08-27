"""Tests for A18 Valuation Extraction Agent
(`app.agents.fair_allocator.valuation_extraction_agent`).

PHASES.md Phase 8's own acceptance list, this module's share of it:
- Complaints + interview answers + voice notes + observed history ->
  cardinal cost matrix, written as a real `ValuationProfile`.
- **Adversarial: genuinely thin evidence produces a sparse matrix, never
  a fabricated dense one** (spec §15.8 A18's own named failure mode).
- Forbidden: no import of `app.solvers.fair_allocation` anywhere.

Unit tests only (fake Gemini, no network; `FakeGraphWriter` +
`InMemoryIdempotencyStore` test doubles in place of the Firestore
emulator for the T3 write path).
"""

from __future__ import annotations

import ast
import inspect
import json
import types

import pytest
from contracts.graph_types import Derivation, NodeId, ValuationProfile
from contracts.tools import PermissionTier

from app.agents.fair_allocator import valuation_extraction_agent
from app.agents.fair_allocator.types import ObservedEffortSignal, ValuationExtractionRequest
from app.agents.fair_allocator.valuation_extraction_agent import AGENT_ID, ValuationExtractionAgent
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_TASK_DESCRIPTIONS = {
    "t-1": "two weekly school runs",
    "t-2": "calling the plumber",
    "t-3": "grocery run",
}


def _agent(*, texts: list[str]) -> tuple[ValuationExtractionAgent, FakeGraphWriter]:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    writer = FakeGraphWriter()
    agent = ValuationExtractionAgent(
        gemini_client=client, graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()
    )
    return agent, writer


def _request(
    *,
    candidate_task_ids: tuple[NodeId, ...] = (NodeId("t-1"), NodeId("t-2"), NodeId("t-3")),
    complaint_texts: tuple[str, ...] = (),
    comparative_preferences: tuple[object, ...] = (),
    voice_note_texts: tuple[str, ...] = (),
    observed_effort: tuple[ObservedEffortSignal, ...] = (),
) -> ValuationExtractionRequest:
    return ValuationExtractionRequest(
        person_id=NodeId("person-priya"),
        allocation_cycle_id="cycle-2026-08",
        candidate_task_ids=candidate_task_ids,
        task_descriptions=_TASK_DESCRIPTIONS,
        complaint_texts=complaint_texts,
        comparative_preferences=comparative_preferences,  # type: ignore[arg-type]
        voice_note_texts=voice_note_texts,
        observed_effort=observed_effort,
    )


class TestWellEvidencedExtractionWritesProfile:
    def test_confident_costs_are_written(self) -> None:
        response = json.dumps(
            {
                "task_costs": [
                    {
                        "task_id": "t-1",
                        "cost": 8.0,
                        "confidence": 0.9,
                        "reasoning": "constant complaints and never actually done by anyone else",
                    },
                    {
                        "task_id": "t-2",
                        "cost": 2.0,
                        "confidence": 0.85,
                        "reasoning": "done once, minor complaint",
                    },
                ]
            }
        )
        agent, writer = _agent(texts=[response])
        request = _request(complaint_texts=("ugh the school run again",), observed_effort=())

        result = agent.extract(request)

        assert result.costs == {"t-1": 8.0, "t-2": 2.0}
        assert NodeId("t-3") in result.omitted_task_ids
        assert result.elicitation_method == "complaint_inference"
        assert result.confidence == pytest.approx((0.9 + 0.85) / 2)
        written = writer.nodes[result.valuation_profile_id]
        assert isinstance(written, ValuationProfile)
        assert written.costs == {"t-1": 8.0, "t-2": 2.0}
        assert written.person_id == NodeId("person-priya")
        assert written.provenance.derivation is Derivation.AMBIGUOUS
        assert written.provenance.source_ref is None
        assert any(edge.edge_type.value == "valuation_of" for edge in writer.edges)


class TestSparseMatrixNeverFabricated:
    """The adversarial proof this phase's work order names explicitly:
    genuinely thin evidence produces a sparse matrix, not a fabricated
    dense one."""

    def test_task_with_no_real_evidence_is_omitted_even_when_model_tries_to_price_it(self) -> None:
        """Even if the (adversarial/hallucinating) model returns a cost
        for every candidate task, a low-confidence entry must still be
        dropped — sparse by omission is enforced by this module, not left
        entirely to the prompt's own instruction."""
        response = json.dumps(
            {
                "task_costs": [
                    {"task_id": "t-1", "cost": 5.0, "confidence": 0.9, "reasoning": "real evidence"},
                    {"task_id": "t-2", "cost": 3.0, "confidence": 0.2, "reasoning": "just guessing, thin"},
                ]
            }
        )
        agent, _ = _agent(texts=[response])
        request = _request(complaint_texts=("only one real complaint",))

        result = agent.extract(request)

        assert result.costs == {"t-1": 5.0}
        assert set(result.omitted_task_ids) == {NodeId("t-2"), NodeId("t-3")}

    def test_model_honestly_omitting_everything_produces_a_fully_sparse_profile(self) -> None:
        """The honest "no confident evidence for anything" case — an
        empty `costs` dict, not a fabricated placeholder set."""
        response = json.dumps({"task_costs": []})
        agent, writer = _agent(texts=[response])
        request = _request(complaint_texts=("something vague and unrelated",))

        result = agent.extract(request)

        assert result.costs == {}
        assert set(result.omitted_task_ids) == {NodeId("t-1"), NodeId("t-2"), NodeId("t-3")}
        assert result.confidence == 0.0
        written = writer.nodes[result.valuation_profile_id]
        assert isinstance(written, ValuationProfile)
        assert written.costs == {}

    def test_negative_cost_from_model_is_dropped_not_written(self) -> None:
        response = json.dumps(
            {"task_costs": [{"task_id": "t-1", "cost": -3.0, "confidence": 0.99, "reasoning": "bad output"}]}
        )
        agent, _ = _agent(texts=[response])
        request = _request(complaint_texts=("x",))

        result = agent.extract(request)

        assert result.costs == {}

    def test_hallucinated_task_id_is_ignored(self) -> None:
        response = json.dumps(
            {"task_costs": [{"task_id": "t-ghost", "cost": 5.0, "confidence": 0.9, "reasoning": "n/a"}]}
        )
        agent, _ = _agent(texts=[response])
        request = _request(complaint_texts=("x",))

        result = agent.extract(request)

        assert result.costs == {}
        assert set(result.omitted_task_ids) == {NodeId("t-1"), NodeId("t-2"), NodeId("t-3")}


class TestObservedEffortEvidence:
    def test_observed_history_contributes_to_elicitation_method(self) -> None:
        response = json.dumps(
            {
                "task_costs": [
                    {"task_id": "t-3", "cost": 1.0, "confidence": 0.8, "reasoning": "does this every week"}
                ]
            }
        )
        agent, _ = _agent(texts=[response])
        request = _request(
            observed_effort=(
                ObservedEffortSignal(
                    task_id=NodeId("t-3"), purchase_item_id=NodeId("item-1"), description="groceries"
                ),
            )
        )

        result = agent.extract(request)

        assert result.elicitation_method == "observed_history"

    def test_mixed_sources_reported_as_mixed(self) -> None:
        response = json.dumps({"task_costs": []})
        agent, _ = _agent(texts=[response])
        request = _request(
            complaint_texts=("complains a lot",),
            observed_effort=(
                ObservedEffortSignal(
                    task_id=NodeId("t-3"), purchase_item_id=NodeId("item-1"), description="groceries"
                ),
            ),
        )

        result = agent.extract(request)

        assert result.elicitation_method == "mixed"


class TestNoEvidenceAtAll:
    def test_raises_value_error_rather_than_silently_extracting_nothing(self) -> None:
        agent, _ = _agent(texts=["{}"])
        request = _request()

        with pytest.raises(ValueError, match="no evidence"):
            agent.extract(request)


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _ = _agent(texts=["{}"])
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        agent, _ = _agent(texts=["{}"])
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)
        assert not agent.tool_registry.has_tier(PermissionTier.T6_FINANCIAL)


def _references_fair_allocation_solver(module: types.ModuleType) -> bool:
    """AST-based, not a raw text search — see
    `test_interviewer_agent.py`'s identical helper for why."""
    tree = ast.parse(inspect.getsource(module))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and "fair_allocation" in node.module:
            return True
        if isinstance(node, ast.Import) and any("fair_allocation" in alias.name for alias in node.names):
            return True
    return False


class TestForbiddenBehaviour:
    """spec §15.8 A18 forbidden list: 'solving.'"""

    def test_module_has_no_import_of_the_solver(self) -> None:
        assert not _references_fair_allocation_solver(valuation_extraction_agent)


def test_agent_id_is_a18() -> None:
    assert str(AGENT_ID) == "A18"
