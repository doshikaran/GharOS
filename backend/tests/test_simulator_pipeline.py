"""Package-level integration test for the Household Simulator (A35-A40,
`app.agents.simulator`) — Phase 11's Gate 11 acceptance requirement: a
full pipeline run against a real fixture graph, not "a `DecisionBrief` was
returned."

Two full runs, each with real data flowing through every stage:

1. **Forward mode**: frame -> ground (2 branches, run independently) ->
   simulate (2 branches, proven structurally independent) -> critique ->
   calibrate -> synthesize. Asserts the final `DecisionBrief`'s content
   traces back to the fixture graph's real nodes — the real `Decision`
   question A35 wrote, the real anchor-derived blast radii A37 computed,
   and A38's real critique text actually present on the `Branch` nodes
   handed to A40.
2. **Backward mode**: `frame_backward` -> `CalibrationAgent.narrate` on a
   real category tag -> `synthesize_backward`, asserting `BackwardModeAnalysis`
   cites real `Outcome` ids drawn from the same fixture's ranked outcomes.

One shared `FakeModels` queue (`_gemini_fakes.FakeModels`) backs every
agent's `GeminiClient` in a run, in exact call order, so this test also
proves the pipeline's real call sequence, not just each stage in
isolation.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from contracts.graph_types import (
    AgentId,
    Branch,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Decision,
    DecisionStatus,
    Derivation,
    Edge,
    EdgeType,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Person,
    PersonRole,
    Provenance,
    PurchaseItem,
)

from app.agents.simulator import context as simulator_context
from app.agents.simulator.calibration_agent import CalibrationAgent
from app.agents.simulator.consistency_critic_agent import ConsistencyCriticAgent
from app.agents.simulator.decision_framing_agent import DecisionFramingAgent
from app.agents.simulator.decision_synthesizer_agent import DecisionSynthesizerAgent
from app.agents.simulator.grounding_research_agent import GroundingResearchAgent
from app.agents.simulator.path_simulator_agent import PathSimulatorAgent
from app.agents.simulator.types import (
    BackwardFramingRequest,
    BackwardSynthesisRequest,
    CritiqueRequest,
    DecisionFramingRequest,
    GroundingRequest,
    PathSimulationRequest,
)
from app.reasoning.gemini_client import GeminiClient

from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


class _SyncedGraphStore:
    """A single in-memory dict backing both `GraphReader` and `GraphWriter`
    for this integration test only — writes are immediately visible to
    reads, unlike this package's split `FakeGraphReader`/`FakeGraphWriter`
    unit-test doubles, because this test exercises real writer -> reader
    handoffs across A35 -> A37 -> A38 within one fixture graph (A37's
    `Branch` write must be readable by A38's critique pass; A38's
    `supersede_node` must be resolvable back to "the current version of
    this branch" for A40, exactly as the real
    `FirestoreDecisionRepository.branches_for` would resolve it for a real
    caller — `current_node` below is this test's own stand-in for that
    resolution, not a change to any agent's own code).
    """

    def __init__(
        self,
        *,
        nodes_by_id: dict[str, object] | None = None,
        blast_radius_multi_by_ids: dict[tuple[str, ...], tuple[object, ...]] | None = None,
        outcome_variance_by_tag: dict[str, tuple[Outcome, ...]] | None = None,
    ) -> None:
        self.nodes: dict[str, object] = dict(nodes_by_id or {})
        self.edges: list[Edge] = []
        self._blast_radius_multi_by_ids = blast_radius_multi_by_ids or {}
        self._outcome_variance_by_tag = outcome_variance_by_tag or {}
        self._supersedes: dict[str, str] = {}

    # -- GraphWriter -------------------------------------------------
    def write_node(self, node: Any) -> NodeId:
        self.nodes[str(node.id)] = node
        return node.id  # type: ignore[no-any-return]

    def write_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def supersede_node(self, old_node_id: NodeId, new_node: Any) -> NodeId:
        self.nodes[str(new_node.id)] = new_node
        self._supersedes[str(old_node_id)] = str(new_node.id)
        return new_node.id  # type: ignore[no-any-return]

    def current_node(self, original_id: NodeId) -> object | None:
        """Test-only resolution of "the current version of this node" —
        follows the `supersede_node` chain, mirroring what a real
        decision-scoped repository query resolves for a real caller."""
        current_id = str(original_id)
        seen: set[str] = set()
        while current_id in self._supersedes and current_id not in seen:
            seen.add(current_id)
            current_id = self._supersedes[current_id]
        return self.nodes.get(current_id)

    # -- GraphReader (only the operations A37/A38/A39 actually use) --
    def get_node(self, node_id: NodeId) -> object | None:
        return self.nodes.get(str(node_id))

    def neighbours(self, node_id: NodeId, edge_type: EdgeType) -> tuple[object, ...]:
        raise NotImplementedError

    def path(self, from_id: NodeId, to_id: NodeId) -> tuple[Edge, ...]:
        raise NotImplementedError

    def blast_radius(self, node_id: NodeId, depth: int) -> tuple[object, ...]:
        raise NotImplementedError

    def blast_radius_multi(self, node_ids: tuple[NodeId, ...], depth: int) -> tuple[object, ...]:
        key = tuple(str(n) for n in node_ids)
        return self._blast_radius_multi_by_ids.get(key, ())

    def conflicts(self, scope: str) -> tuple[Edge, ...]:
        raise NotImplementedError

    def dependency_chain(self, obligation_id: NodeId, *, max_depth: int = 25) -> tuple[Obligation, ...]:
        raise NotImplementedError

    def load(self, person_id: NodeId, window: tuple[datetime, datetime]) -> float:
        raise NotImplementedError

    def series(self, commitment_id: NodeId) -> tuple[object, ...]:
        raise NotImplementedError

    def history(self, entity_id: NodeId) -> tuple[Outcome, ...]:
        raise NotImplementedError

    def outcome_variance(self, tag: str) -> tuple[Outcome, ...]:
        return self._outcome_variance_by_tag.get(tag, ())

    def decisions_touching(self, entity_id: NodeId) -> tuple[Decision, ...]:
        raise NotImplementedError

    def concession_ledger(self, person_id: NodeId) -> tuple[Decision, ...]:
        raise NotImplementedError

    def unexplained(self, scope: str) -> tuple[NodeId, ...]:
        raise NotImplementedError

    def unverified(self, scope: str) -> tuple[NodeId, ...]:
        raise NotImplementedError

    def expected_but_absent(self, constraint_id: NodeId) -> tuple[NodeId, ...]:
        raise NotImplementedError

    def spend_by_category(self, window: tuple[datetime, datetime]) -> dict[str, float]:
        raise NotImplementedError

    def effort_evidence(
        self, person_id: NodeId, window: tuple[datetime, datetime]
    ) -> tuple[PurchaseItem, ...]:
        raise NotImplementedError


def _provenance(agent: str) -> Provenance:
    # AMBIGUOUS/no source_ref — these fixtures stand in for real household
    # entities already on the graph; only EXTRACTED/INFERRED provenance
    # requires a real SourceRef (contracts.graph_types.Provenance).
    return Provenance(
        derivation=Derivation.AMBIGUOUS,
        source_ref=None,
        confidence=0.9,
        deriving_agent=AgentId(agent),
        created_at=_NOW,
    )


def _person(node_id: str, name: str) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=_provenance("A3"),
        display_name=name,
        aliases=(),
        role=PersonRole.ELDER,
        can_drive=False,
        can_sign=True,
        has_bank_access=False,
        has_medical_proxy=False,
        contact_channels=(),
        language_profile=LanguageProfile(
            primary_language="en",
            languages_understood=("en",),
            script_preference="latin",
            code_mixing_profile=None,
            formality_preference=None,
            literacy_mode=LiteracyMode.TEXT_CAPABLE,
        ),
    )


def _obligation(node_id: str, title: str) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=_provenance("A3"),
        title=title,
        obligation_type="school",
        due_at=None,
        must_start_by=None,
        effort_estimate_minutes=None,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _constraint(node_id: str, original_text: str) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=_provenance("A3"),
        kind=ConstraintKind.SCHEDULE,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={},
        original_text=original_text,
    )


def _outcome(node_id: str, *, predicted: str, actual: str, variance: float | None, tag: str) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=_provenance("A26"),
        predicted=predicted,
        actual=actual,
        variance=variance,
        attribution_tags=(tag,),
    )


class TestForwardModeFullPipeline:
    def test_frame_ground_simulate_critique_calibrate_synthesize(self) -> None:
        priya_mother = _person("person-priya-mother", "Priya's mother")
        board_exam = _constraint(
            "constraint-board-exam", "daughter is in her board-exam year (10th standard) this academic year"
        )
        school_fee = _obligation("obligation-school-fee", "school fee due next term")

        anchors_stay = (NodeId("person-priya-mother"),)
        anchors_move = (NodeId("constraint-board-exam"), NodeId("obligation-school-fee"))

        past_relocation_outcomes = (
            _outcome("outcome-r1", predicted="p1", actual="a1", variance=6.0, tag="relocation"),
            _outcome("outcome-r2", predicted="p2", actual="a2", variance=-9.0, tag="relocation"),
            _outcome("outcome-r3", predicted="p3", actual="a3", variance=2.0, tag="relocation"),
        )

        store = _SyncedGraphStore(
            nodes_by_id={
                "person-priya-mother": priya_mother,
                "constraint-board-exam": board_exam,
                "obligation-school-fee": school_fee,
            },
            blast_radius_multi_by_ids={
                anchors_stay: (priya_mother,),
                anchors_move: (board_exam, school_fee),
            },
            outcome_variance_by_tag={"relocation": past_relocation_outcomes},
        )

        texts = [
            # 0: A35 frame()
            json.dumps(
                {
                    "question": "Should the household relocate to Bangalore or remain in Mumbai?",
                    "is_false_binary": True,
                    "unconsidered_options": [
                        "A hybrid arrangement where Raj travels to Bangalore part-time instead of "
                        "a full household relocation."
                    ],
                }
            ),
            # 1-2: A36 ground(stay_in_mumbai) — honest empty citations path
            json.dumps({"search_query": "in-home elder care Mumbai 2026"}),
            "no grounded findings for in-home elder care",
            # 3-4: A36 ground(move_to_bangalore)
            json.dumps({"search_query": "school transfer mid-year Bangalore 2026"}),
            "no grounded findings for school transfers",
            # 5: A37 simulate(stay_in_mumbai)
            json.dumps(
                {
                    "projected_impacts": {
                        "care_continuity": "Grandma stays near her existing dialysis clinic in Mumbai."
                    }
                }
            ),
            # 6: A37 simulate(move_to_bangalore)
            json.dumps(
                {
                    "projected_impacts": {
                        "school": "Daughter would need a mid-year school transfer during her board-exam year."
                    }
                }
            ),
            # 7: A38 critique(stay_in_mumbai)
            json.dumps(
                {
                    "over_optimistic_claims": [],
                    "omitted_second_order_effects": [],
                    "revised_confidence_note": "This projection held up under adversarial review.",
                }
            ),
            # 8: A38 critique(move_to_bangalore)
            json.dumps(
                {
                    "over_optimistic_claims": [
                        "The projection does not weigh the real hard board-exam-year schedule "
                        "constraint already on file against a mid-year school transfer."
                    ],
                    "omitted_second_order_effects": [
                        "No mention of the school fee obligation already due next term."
                    ],
                    "revised_confidence_note": (
                        "Confidence downgraded once weighed against the board-exam-year constraint."
                    ),
                }
            ),
            # 9: A39 calibration.narrate("relocation")
            json.dumps(
                {
                    "narrative": "Past relocations in this household have historically run over schedule."
                }
            ),
            # 10: A40 synthesize()
            json.dumps(
                {
                    "branch_summaries": {
                        "stay_in_mumbai": "Keeps Grandma near her existing dialysis clinic.",
                        "move_to_bangalore": "Risks a mid-year school transfer during the board-exam year.",
                    },
                    "trade_offs": [
                        "Continuity of elder care in Mumbai versus proximity to Raj's new role in "
                        "Bangalore."
                    ],
                    "open_questions": ["Would the school accept a mid-year transfer at all?"],
                }
            ),
        ]
        fake_models = FakeModels(texts=texts)
        client = GeminiClient(router=fake_router(fake_models))
        idempotency_store = InMemoryIdempotencyStore()

        # -- A35 Decision Framing -----------------------------------
        framing_agent = DecisionFramingAgent(
            gemini_client=client, graph_writer=store, idempotency_store=idempotency_store
        )
        frame = framing_agent.frame(
            DecisionFramingRequest(
                household_request_text="Should we move to Bangalore or stay in Mumbai?",
                trigger="Raj's company offered a Bangalore relocation package",
                proposed_branch_labels=("stay_in_mumbai", "move_to_bangalore"),
                known_household_context=(
                    "Priya's mother lives nearby and has twice-weekly dialysis.",
                    "Their daughter is in her board-exam year this academic year.",
                ),
            ),
            cycle_id="cycle-forward",
        )
        assert frame.is_false_binary is True
        real_decision = store.get_node(frame.decision_id)
        assert isinstance(real_decision, Decision)
        assert real_decision.status is DecisionStatus.OPEN

        # -- A36 Grounding/Research, run independently per branch ---
        grounding_agent = GroundingResearchAgent(gemini_client=client)
        grounding_stay = grounding_agent.research(
            GroundingRequest(
                branch_label="stay_in_mumbai",
                topic="in-home elder care costs and availability in Mumbai",
                household_context="household of 4, elder on dialysis, child in board-exam year",
            )
        )
        grounding_move = grounding_agent.research(
            GroundingRequest(
                branch_label="move_to_bangalore",
                topic="mid-year school transfer availability in Bangalore",
                household_context="household of 4, elder on dialysis, child in board-exam year",
            )
        )
        assert grounding_stay.citations == ()
        assert grounding_move.citations == ()

        # -- A37 Path Simulator, per branch, structurally independent -
        simulator_agent = PathSimulatorAgent(
            gemini_client=client, graph_reader=store, graph_writer=store, idempotency_store=idempotency_store
        )
        projection_stay = simulator_agent.simulate(
            PathSimulationRequest(
                decision_id=frame.decision_id,
                branch_label="stay_in_mumbai",
                branch_topic="staying in Mumbai near existing elder care",
                candidate_anchor_ids=anchors_stay,
                grounding=grounding_stay,
            ),
            cycle_id="cycle-forward",
        )
        projection_move = simulator_agent.simulate(
            PathSimulationRequest(
                decision_id=frame.decision_id,
                branch_label="move_to_bangalore",
                branch_topic="relocating to Bangalore",
                candidate_anchor_ids=anchors_move,
                grounding=grounding_move,
            ),
            cycle_id="cycle-forward",
        )
        # Independence: disjoint, traceable blast radii, no cross-branch leakage.
        assert projection_stay.blast_radius_node_ids == (NodeId("person-priya-mother"),)
        assert projection_move.blast_radius_node_ids == (
            NodeId("constraint-board-exam"),
            NodeId("obligation-school-fee"),
        )
        assert set(projection_stay.blast_radius_node_ids).isdisjoint(projection_move.blast_radius_node_ids)
        assert "care_continuity" in projection_stay.projected_impacts
        assert "school" in projection_move.projected_impacts
        assert "school" not in projection_stay.projected_impacts

        # -- A38 Consistency Critic, per branch ----------------------
        critic_agent = ConsistencyCriticAgent(
            gemini_client=client, graph_reader=store, graph_writer=store, idempotency_store=idempotency_store
        )
        blast_context_stay = simulator_context.summarize_anchor_nodes(
            tuple(store.get_node(nid) for nid in projection_stay.blast_radius_node_ids)
        )
        blast_context_move = simulator_context.summarize_anchor_nodes(
            tuple(store.get_node(nid) for nid in projection_move.blast_radius_node_ids)
        )
        critique_stay = critic_agent.critique(
            CritiqueRequest(
                branch_projection=projection_stay,
                branch_topic="staying in Mumbai",
                blast_radius_context=blast_context_stay,
            ),
            cycle_id="cycle-forward",
        )
        critique_move = critic_agent.critique(
            CritiqueRequest(
                branch_projection=projection_move,
                branch_topic="relocating to Bangalore",
                blast_radius_context=blast_context_move,
            ),
            cycle_id="cycle-forward",
        )
        assert critique_stay.over_optimistic_claims == ()
        assert "board-exam-year" in critique_move.over_optimistic_claims[0]

        current_branch_stay = store.current_node(projection_stay.branch_id)
        current_branch_move = store.current_node(projection_move.branch_id)
        assert isinstance(current_branch_stay, Branch)
        assert isinstance(current_branch_move, Branch)
        assert len(current_branch_stay.critiques) == 1
        assert len(current_branch_move.critiques) == 1
        assert "board-exam" in current_branch_move.critiques[0]

        # -- A39 Calibration ------------------------------------------
        calibration_agent = CalibrationAgent(gemini_client=client, graph_reader=store)
        calibration = calibration_agent.narrate("relocation")
        assert calibration.estimate.sample_size == 3
        assert calibration.estimate.is_thin_history is False

        # -- A40 Decision Synthesizer -----------------------------------
        synthesizer_agent = DecisionSynthesizerAgent(gemini_client=client)
        brief = synthesizer_agent.synthesize(
            decision=real_decision,
            branches=(current_branch_stay, current_branch_move),
            calibrations=(calibration,),
        )

        # Traceable to the real fixture graph, not just "a brief came back."
        assert brief.decision_id == frame.decision_id == real_decision.id
        assert any("stay_in_mumbai" in s for s in brief.branch_summaries)
        assert any("move_to_bangalore" in s for s in brief.branch_summaries)
        assert any("dialysis" in s for s in brief.branch_summaries)
        assert any("board-exam" in s for s in brief.branch_summaries)
        assert len(fake_models.calls) == len(texts)


class TestBackwardModeFullPipeline:
    def test_frame_backward_calibrate_synthesize_backward(self) -> None:
        past_relocation_outcomes = (
            _outcome("outcome-b1", predicted="6 weeks", actual="14 weeks", variance=8.0, tag="relocation"),
            _outcome(
                "outcome-b2", predicted="on budget", actual="20% over budget", variance=-5.0, tag="relocation"
            ),
            _outcome("outcome-b3", predicted="smooth", actual="smooth", variance=0.5, tag="relocation"),
        )
        store = _SyncedGraphStore(outcome_variance_by_tag={"relocation": past_relocation_outcomes})

        texts = [
            # 0: A39 calibration.narrate("relocation")
            json.dumps(
                {"narrative": "Past relocations here have historically taken far longer than planned."}
            ),
            # 1: A40 synthesize_backward()
            json.dumps(
                {
                    "assumed_failure_point": (
                        "The relocation likely slipped its timeline the way the last one did — it "
                        "took more than double the planned 6 weeks."
                    ),
                    "supporting_outcome_ids": ["outcome-b1"],
                    "suggested_mitigations": [
                        "Build an explicit multi-week schedule buffer into the relocation plan."
                    ],
                }
            ),
        ]
        fake_models = FakeModels(texts=texts)
        client = GeminiClient(router=fake_router(fake_models))
        idempotency_store = InMemoryIdempotencyStore()

        framing_agent = DecisionFramingAgent(
            gemini_client=client, graph_writer=store, idempotency_store=idempotency_store
        )
        frame = framing_agent.frame_backward(
            BackwardFramingRequest(
                plan_description="We relocated the household to Bangalore in June 2026",
                category_tag="relocation",
            ),
            cycle_id="cycle-backward",
        )
        assert frame.is_false_binary is False
        assert frame.unconsidered_options == ()
        assert len(fake_models.calls) == 0  # frame_backward is deterministic

        calibration_agent = CalibrationAgent(gemini_client=client, graph_reader=store)
        calibration = calibration_agent.narrate("relocation")
        assert calibration.estimate.sample_size == 3

        synthesizer_agent = DecisionSynthesizerAgent(gemini_client=client)
        analysis = synthesizer_agent.synthesize_backward(
            BackwardSynthesisRequest(
                frame=frame,
                calibration=calibration,
                plan_description="We relocated the household to Bangalore in June 2026",
            )
        )

        assert analysis.plan_description == "We relocated the household to Bangalore in June 2026"
        assert analysis.supporting_outcome_ids == (NodeId("outcome-b1"),)
        assert analysis.assumed_failure_point.strip() != ""
        assert analysis.confidence_note == calibration.narrative
        assert len(fake_models.calls) == 2
