"""Tests for A49 Council Recorder (`app.agents.council.recorder`).

Covers: the strict 1:1 write count (one `CouncilPosition` per specialist/
delegate/adversary output, never a summary), content fidelity (each
written position's `reasoning`/`evidence_refs` matches its own source
input, never a blend of two), `CONCEDED_BY` edges per real concession,
T3-only tool registry, and that this module holds no `GeminiClient`
dependency at all (deterministic, no model call).
"""

from __future__ import annotations

import inspect

import pytest
from contracts.graph_types import AgentId, CouncilPosition, EdgeType, NodeId, ValuationProfile
from contracts.tools import PermissionTier

from app.agents.council.recorder import AGENT_ID, CouncilRecorderAgent
from app.agents.council.types import AdversaryAttack, DelegateScoring, RecorderRequest, SpecialistPosition
from app.arbitration.gated_tool import ReferenceGatedTool
from app.solvers.council_arbiter import CouncilResolution
from app.tools.errors import GatedToolRegistrationDenied

from ._council_fixtures import provenance
from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore


def _valuation_profile(person_id: str, costs: dict[str, float]) -> ValuationProfile:
    return ValuationProfile(
        id=NodeId(f"valuation-profile:{person_id}"),
        provenance=provenance(),
        person_id=NodeId(person_id),
        costs=costs,
        elicitation_method="observed_history",
    )


def _resolution(*, winning_branch_id: str, conceding_person_ids: tuple[str, ...]) -> CouncilResolution:
    return CouncilResolution(
        winning_branch_id=NodeId(winning_branch_id),
        regret_by_person={NodeId(p): 5.0 for p in conceding_person_ids},
        most_costly_to=NodeId(conceding_person_ids[0]) if conceding_person_ids else None,
        most_favorable_to=NodeId(conceding_person_ids[0]) if conceding_person_ids else None,
        conceding_person_ids=tuple(NodeId(p) for p in conceding_person_ids),
        eliminated_branch_ids=(),
    )


def _recorder() -> tuple[CouncilRecorderAgent, FakeGraphWriter]:
    writer = FakeGraphWriter()
    return CouncilRecorderAgent(graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()), writer


class TestOneToOneWrapDiscipline:
    def test_writes_exactly_one_position_per_specialist_delegate_and_adversary_output(self) -> None:
        recorder, writer = _recorder()
        finance_position = SpecialistPosition(
            agent_id="A42",
            stance="supports",
            reasoning="Affordable given savings.",
            evidence_refs=("e1",),
            eliminated_branch_ids=(),
        )
        care_position = SpecialistPosition(
            agent_id="A43",
            stance="opposes",
            reasoning="Door sill too high.",
            evidence_refs=("e2",),
            eliminated_branch_ids=(NodeId("branch-b"),),
        )
        dad_scoring = DelegateScoring(
            person_id=NodeId("person-dad"),
            valuation_profile=_valuation_profile("person-dad", {"branch-a": 3.0, "branch-c": 9.0}),
            reasoning="Dad prefers boot space.",
        )
        mum_scoring = DelegateScoring(
            person_id=NodeId("person-mum"),
            valuation_profile=_valuation_profile("person-mum", {"branch-a": 1.0}),
            reasoning="Mum prefers fuel economy.",
        )
        attack = AdversaryAttack(
            target_branch_id=NodeId("branch-a"),
            critique="This household underestimated maintenance before.",
            cited_outcome_ids=(NodeId("outcome-1"),),
        )
        resolution = _resolution(winning_branch_id="branch-a", conceding_person_ids=("person-mum",))

        request = RecorderRequest(
            decision_id=NodeId("decision-1"),
            specialist_positions=(finance_position, care_position),
            delegate_scorings=(dad_scoring, mum_scoring),
            adversary_attack=attack,
            resolution=resolution,
        )

        result = recorder.record(request, cycle_id="cycle-1")

        written_positions = [n for n in writer.nodes.values() if isinstance(n, CouncilPosition)]
        assert len(written_positions) == 5  # 2 specialists + 2 delegates + 1 adversary
        assert len(result.position_ids) == 5

    def test_specialist_position_content_matches_its_own_source_verbatim(self) -> None:
        recorder, writer = _recorder()
        finance_position = SpecialistPosition(
            agent_id="A42",
            stance="supports",
            reasoning="Affordable given real savings trajectory.",
            evidence_refs=("ledger-event-1", "commitment-1"),
            eliminated_branch_ids=(),
        )
        request = RecorderRequest(
            decision_id=NodeId("decision-1"),
            specialist_positions=(finance_position,),
            delegate_scorings=(),
            adversary_attack=AdversaryAttack(
                target_branch_id=NodeId("branch-a"), critique="No precedent found.", cited_outcome_ids=()
            ),
            resolution=_resolution(winning_branch_id="branch-a", conceding_person_ids=()),
        )

        result = recorder.record(request, cycle_id="cycle-2")

        finance_written = next(
            n
            for n in writer.nodes.values()
            if isinstance(n, CouncilPosition) and n.held_by_agent == AgentId("A42")
        )
        assert finance_written.reasoning == finance_position.reasoning
        assert finance_written.evidence_refs == finance_position.evidence_refs
        assert finance_written.stance == finance_position.stance
        assert finance_written.decision_id == NodeId("decision-1")
        assert finance_written.branch_id is None
        assert len(result.position_ids) == 2  # 1 specialist + 1 adversary

    def test_delegate_position_reasoning_is_never_blended_with_another_delegates(self) -> None:
        recorder, writer = _recorder()
        dad_scoring = DelegateScoring(
            person_id=NodeId("person-dad"),
            valuation_profile=_valuation_profile("person-dad", {"branch-a": 3.0}),
            reasoning="Dad's own real reasoning, about boot space.",
        )
        mum_scoring = DelegateScoring(
            person_id=NodeId("person-mum"),
            valuation_profile=_valuation_profile("person-mum", {"branch-a": 1.0}),
            reasoning="Mum's own real reasoning, about fuel economy.",
        )
        request = RecorderRequest(
            decision_id=NodeId("decision-1"),
            specialist_positions=(),
            delegate_scorings=(dad_scoring, mum_scoring),
            adversary_attack=AdversaryAttack(
                target_branch_id=NodeId("branch-a"), critique="No precedent found.", cited_outcome_ids=()
            ),
            resolution=_resolution(winning_branch_id="branch-a", conceding_person_ids=()),
        )

        recorder.record(request, cycle_id="cycle-3")

        delegate_positions = [
            n
            for n in writer.nodes.values()
            if isinstance(n, CouncilPosition) and n.held_by_agent == AgentId("A47")
        ]
        assert len(delegate_positions) == 2
        reasonings = {p.reasoning for p in delegate_positions}
        assert reasonings == {dad_scoring.reasoning, mum_scoring.reasoning}
        # Neither delegate's own written reasoning contains the other's text.
        for p in delegate_positions:
            other_reasoning = (
                mum_scoring.reasoning if p.reasoning == dad_scoring.reasoning else dad_scoring.reasoning
            )
            assert other_reasoning not in p.reasoning
        assert all(p.stance == "neutral" for p in delegate_positions)

    def test_adversary_position_carries_the_targeted_branch_and_real_cited_ids(self) -> None:
        recorder, writer = _recorder()
        attack = AdversaryAttack(
            target_branch_id=NodeId("branch-a"),
            critique="Real critique text.",
            cited_outcome_ids=(NodeId("outcome-1"), NodeId("outcome-2")),
        )
        request = RecorderRequest(
            decision_id=NodeId("decision-1"),
            specialist_positions=(),
            delegate_scorings=(),
            adversary_attack=attack,
            resolution=_resolution(winning_branch_id="branch-a", conceding_person_ids=()),
        )

        recorder.record(request, cycle_id="cycle-4")

        (adversary_position,) = [
            n
            for n in writer.nodes.values()
            if isinstance(n, CouncilPosition) and n.held_by_agent == AgentId("A48")
        ]
        assert adversary_position.reasoning == attack.critique
        assert adversary_position.branch_id == NodeId("branch-a")
        assert adversary_position.stance == "opposes"
        assert adversary_position.evidence_refs == ("outcome-1", "outcome-2")


class TestConcededByEdges:
    def test_one_edge_per_conceding_person(self) -> None:
        recorder, writer = _recorder()
        request = RecorderRequest(
            decision_id=NodeId("decision-1"),
            specialist_positions=(),
            delegate_scorings=(),
            adversary_attack=AdversaryAttack(
                target_branch_id=NodeId("branch-a"), critique="x", cited_outcome_ids=()
            ),
            resolution=_resolution(
                winning_branch_id="branch-a", conceding_person_ids=("person-mum", "person-elder")
            ),
        )

        result = recorder.record(request, cycle_id="cycle-5")

        conceded_edges = [e for e in writer.edges if e.edge_type is EdgeType.CONCEDED_BY]
        assert len(conceded_edges) == 2
        assert {e.to_id for e in conceded_edges} == {NodeId("person-mum"), NodeId("person-elder")}
        assert all(e.from_id == NodeId("decision-1") for e in conceded_edges)
        assert len(result.conceded_by_edge_ids) == 2

    def test_no_concessions_writes_no_edges(self) -> None:
        recorder, writer = _recorder()
        request = RecorderRequest(
            decision_id=NodeId("decision-1"),
            specialist_positions=(),
            delegate_scorings=(),
            adversary_attack=AdversaryAttack(
                target_branch_id=NodeId("branch-a"), critique="x", cited_outcome_ids=()
            ),
            resolution=_resolution(winning_branch_id="branch-a", conceding_person_ids=()),
        )

        recorder.record(request, cycle_id="cycle-6")

        assert [e for e in writer.edges if e.edge_type is EdgeType.CONCEDED_BY] == []


class TestNeverWritesDecisionStatus:
    def test_recorder_module_never_imports_decisionstatus(self) -> None:
        import ast
        from pathlib import Path

        import app.agents.council.recorder as recorder_module

        assert recorder_module.__file__ is not None
        source_path = Path(recorder_module.__file__)
        tree = ast.parse(source_path.read_text(encoding="utf-8"), filename=str(source_path))
        imported_names = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            for alias in node.names
        }
        assert "DecisionStatus" not in imported_names


class TestDeterministicNoModelCall:
    def test_constructor_has_no_gemini_client_parameter(self) -> None:
        params = inspect.signature(CouncilRecorderAgent.__init__).parameters
        assert "gemini_client" not in params


class TestWriteToolIsT3Only:
    def test_registry_holds_only_a_t3_tool(self) -> None:
        recorder, _writer = _recorder()
        tools = recorder.tool_registry.tools()
        assert len(tools) == 1
        assert tools[0].tier is PermissionTier.T3_INTERNAL_WRITE

    def test_registry_rejects_a_t6_payment_tool(self) -> None:
        recorder, _writer = _recorder()
        payment_tool = ReferenceGatedTool(
            name="payment_executor",
            tier=PermissionTier.T6_FINANCIAL,
            bounds={},
            effect=lambda **kwargs: "paid",
            idempotency_store=InMemoryIdempotencyStore(),
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(recorder.tool_registry, payment_tool)


def test_agent_id_is_a49() -> None:
    assert str(AGENT_ID) == "A49"
