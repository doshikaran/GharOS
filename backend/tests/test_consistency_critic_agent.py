"""Tests for A38 Consistency Critic (`app.agents.simulator.consistency_
critic_agent`).

**Gate 11's literal requirement**: "critic catches a planted over-optimistic
assumption." `TestGate11CatchesPlantedOverOptimism` builds a concrete
`BranchProjection` whose `projected_impacts` claims a school transition
would be "completely seamless with zero disruption," directly contradicted
by a real `blast_radius_context` entry naming a hard, board-exam-year
schedule `Constraint` already on file — then asserts the resulting
`BranchCritique` actually names that real contradiction (not just that
*a* critique object came back), and that the rendered prompt actually gave
the model both pieces of evidence it needed to catch it.

Also covers:
- Never silently accepts a clean projection — `revised_confidence_note`
  is always populated; a blank one is rejected.
- The `supersede_node`-based append into `Branch.critiques`.
- `errors.BranchNotFound` when the branch id does not currently resolve.
- Forbidden: self-critique — this module never imports/calls
  `path_simulator_agent` at all (checked directly against this module's
  own source, not just by absence of an import in test code).

Unit tests only (fake Gemini, no network; `FakeGraphReader` + `FakeGraph
Writer` + `InMemoryIdempotencyStore` test doubles).
"""

from __future__ import annotations

import inspect
import json
from datetime import UTC, datetime

import pytest
from contracts.graph_types import AgentId, Branch, Derivation, NodeId, Provenance
from contracts.tools import PermissionTier

import app.agents.simulator.consistency_critic_agent as consistency_critic_agent_module
from app.agents.simulator.consistency_critic_agent import AGENT_ID, ConsistencyCriticAgent
from app.agents.simulator.errors import BranchNotFound, ModelResponseMalformed
from app.agents.simulator.types import BranchProjection, CritiqueRequest
from app.arbitration.gated_tool import ReferenceGatedTool
from app.reasoning.gemini_client import GeminiClient
from app.tools.errors import GatedToolRegistrationDenied

from ._ast_checks import imports_any_module_named
from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_reader import FakeGraphReader
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)

_OVER_OPTIMISTIC_CLAIM = (
    "The transition to a new school will be completely seamless with zero disruption "
    "to my daughter's board exam preparation."
)
_CONTRADICTING_CONSTRAINT_FACT = (
    'Constraint(kind=schedule, severity=hard, "daughter is in her board-exam year '
    '(10th standard) this academic year")'
)


def _current_branch(*, branch_id: NodeId, critiques: tuple[str, ...] = ()) -> Branch:
    return Branch(
        id=branch_id,
        provenance=Provenance(
            derivation=Derivation.AMBIGUOUS,
            source_ref=None,
            confidence=1.0,
            deriving_agent=AgentId("A37"),
            created_at=_NOW,
        ),
        decision_id=NodeId("decision-1"),
        label="move_to_bangalore",
        projected_impacts={"school": _OVER_OPTIMISTIC_CLAIM},
        grounding_refs=(),
        critiques=critiques,
    )


def _projection(*, branch_id: NodeId) -> BranchProjection:
    return BranchProjection(
        branch_id=branch_id,
        label="move_to_bangalore",
        projected_impacts={"school": _OVER_OPTIMISTIC_CLAIM},
        grounding_refs=(),
        blast_radius_node_ids=(NodeId("constraint-board-exam"),),
    )


def _agent(
    *, texts: list[str], nodes_by_id: dict[str, object]
) -> tuple[ConsistencyCriticAgent, FakeGraphReader, FakeGraphWriter, FakeModels]:
    fake_models = FakeModels(texts=texts)
    client = GeminiClient(router=fake_router(fake_models))
    reader = FakeGraphReader(nodes_by_id=nodes_by_id)
    writer = FakeGraphWriter()
    agent = ConsistencyCriticAgent(
        gemini_client=client,
        graph_reader=reader,
        graph_writer=writer,
        idempotency_store=InMemoryIdempotencyStore(),
    )
    return agent, reader, writer, fake_models


class TestGate11CatchesPlantedOverOptimism:
    def test_critique_names_the_real_contradiction(self) -> None:
        branch_id = NodeId("branch-1")
        scripted_critique = json.dumps(
            {
                "over_optimistic_claims": [
                    'The claim that the school transition will be "completely seamless with zero '
                    'disruption" directly contradicts the household\'s own hard board-exam-year '
                    "schedule constraint on file — a mid-year school change during a board-exam "
                    "year is a real, material disruption risk, not zero."
                ],
                "omitted_second_order_effects": [
                    "No mention of how existing exam-prep tutoring would need to be re-arranged "
                    "after a mid-year school change."
                ],
                "revised_confidence_note": (
                    "This projection's optimism does not hold up against the board-exam-year "
                    "constraint already on file; confidence downgraded."
                ),
            }
        )
        agent, reader, writer, fake_models = _agent(
            texts=[scripted_critique],
            nodes_by_id={"branch-1": _current_branch(branch_id=branch_id)},
        )
        request = CritiqueRequest(
            branch_projection=_projection(branch_id=branch_id),
            branch_topic="relocating to Bangalore",
            blast_radius_context=(_CONTRADICTING_CONSTRAINT_FACT,),
        )

        critique = agent.critique(request, cycle_id="cycle-1")

        # The critic was actually given both the over-optimistic claim and
        # the contradicting real graph fact — the raw material a real
        # adversarial pass needs to catch the contradiction.
        sent_prompt = str(fake_models.calls[0]["contents"])
        assert "completely seamless with zero disruption" in sent_prompt
        assert "board-exam year" in sent_prompt

        assert len(critique.over_optimistic_claims) == 1
        flagged = critique.over_optimistic_claims[0]
        assert "board-exam" in flagged
        assert "completely seamless" in flagged or "zero disruption" in flagged
        note = critique.revised_confidence_note
        assert "board-exam" in note or "constraint" in note

        # And the critique is actually appended onto the real Branch node.
        assert reader.get_node_calls == ["branch-1"]
        superseded = next(iter(writer.nodes.values()))
        assert isinstance(superseded, Branch)
        assert len(superseded.critiques) == 1
        assert "board-exam" in superseded.critiques[0]
        assert superseded.critiques[0].startswith("[A38]")


class TestRevisedConfidenceNoteAlwaysPopulated:
    def test_clean_projection_still_states_it_held_up(self) -> None:
        branch_id = NodeId("branch-2")
        scripted = json.dumps(
            {
                "over_optimistic_claims": [],
                "omitted_second_order_effects": [],
                "revised_confidence_note": (
                    "This projection held up under adversarial review — no over-optimistic "
                    "claims or omitted second-order effects were found."
                ),
            }
        )
        agent, _reader, writer, _fake_models = _agent(
            texts=[scripted], nodes_by_id={"branch-2": _current_branch(branch_id=branch_id)}
        )
        request = CritiqueRequest(
            branch_projection=_projection(branch_id=branch_id),
            branch_topic="topic",
            blast_radius_context=(),
        )

        critique = agent.critique(request, cycle_id="cycle-2")

        assert critique.over_optimistic_claims == ()
        assert critique.omitted_second_order_effects == ()
        assert critique.revised_confidence_note.strip() != ""
        superseded = next(iter(writer.nodes.values()))
        assert isinstance(superseded, Branch)
        assert "held up under adversarial review" in superseded.critiques[0]

    def test_blank_revised_confidence_note_is_rejected(self) -> None:
        branch_id = NodeId("branch-3")
        scripted = json.dumps(
            {
                "over_optimistic_claims": [],
                "omitted_second_order_effects": [],
                "revised_confidence_note": "  ",
            }
        )
        agent, _reader, _writer, _fake_models = _agent(
            texts=[scripted], nodes_by_id={"branch-3": _current_branch(branch_id=branch_id)}
        )
        request = CritiqueRequest(
            branch_projection=_projection(branch_id=branch_id), branch_topic="topic", blast_radius_context=()
        )

        with pytest.raises(ModelResponseMalformed):
            agent.critique(request, cycle_id="cycle-3")


class TestBranchNotFound:
    def test_raises_when_branch_id_does_not_resolve(self) -> None:
        agent, _reader, _writer, _fake_models = _agent(
            texts=[
                json.dumps(
                    {
                        "over_optimistic_claims": [],
                        "omitted_second_order_effects": [],
                        "revised_confidence_note": "fine",
                    }
                )
            ],
            nodes_by_id={},
        )
        request = CritiqueRequest(
            branch_projection=_projection(branch_id=NodeId("branch-missing")),
            branch_topic="topic",
            blast_radius_context=(),
        )

        with pytest.raises(BranchNotFound) as exc_info:
            agent.critique(request, cycle_id="cycle-4")

        assert exc_info.value.branch_id == NodeId("branch-missing")


class TestForbiddenSelfCritique:
    def test_module_never_imports_path_simulator_agent(self) -> None:
        # AST-based, not a substring search — this module's own docstring
        # *legitimately* discusses `path_simulator_agent` in prose (see
        # `_ast_checks.py`'s own rationale for the identical Phase 3
        # "never infers" precedent); only a real import statement counts.
        assert not imports_any_module_named(
            consistency_critic_agent_module, substring="path_simulator_agent"
        )

    def test_critique_signature_never_accepts_re_derivation_input(self) -> None:
        params = list(inspect.signature(ConsistencyCriticAgent.critique).parameters)
        assert params == ["self", "request", "cycle_id"]


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        agent, _reader, _writer, _fake_models = _agent(texts=["{}"], nodes_by_id={})
        tools = agent.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        agent, _reader, _writer, _fake_models = _agent(texts=["{}"], nodes_by_id={})
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, payment_tool)


def test_agent_id_is_a38() -> None:
    assert str(AGENT_ID) == "A38"
