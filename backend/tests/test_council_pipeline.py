"""Package-level integration test for the Household Council (A41-A49,
`app.agents.council`) — Gate 12's own acceptance requirement: a full
pipeline run against real fixture graph data for both spec §12.4 (buying a
car) and §12.5 (buying a house), not "a `CouncilBrief` was returned."

Both runs assert the final `CouncilBrief`'s content is traceable to the
fixture's real facts: a real Care `HARD` constraint eliminating a real
candidate branch, and a real trade-off naming real people (a real
concession, not an invented one).

One shared `FakeModels` queue backs every agent's `GeminiClient` in a run,
in exact call order — mirrors `test_simulator_pipeline.py`'s own
established pattern (Phase 11) for its own package one phase earlier.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest
from contracts.graph_types import ConstraintKind, ConstraintSeverity, CouncilPosition, NodeId

from app.agents.council import pipeline
from app.agents.council.adversary_agent import CouncilAdversaryAgent
from app.agents.council.care_specialist_agent import CareSpecialistAgent
from app.agents.council.convener_agent import CouncilConvenerAgent
from app.agents.council.education_specialist_agent import EducationSpecialistAgent
from app.agents.council.errors import NoSurvivingBranches
from app.agents.council.finance_specialist_agent import FinanceSpecialistAgent
from app.agents.council.legal_specialist_agent import LegalSpecialistAgent
from app.agents.council.logistics_specialist_agent import LogisticsSpecialistAgent
from app.agents.council.member_delegate_agent import MemberDelegateAgent
from app.agents.council.recorder import CouncilRecorderAgent
from app.agents.council.types import ConvenerRequest, HouseholdMemberSummary
from app.graph.scoped_reader import CARE_SCOPE, EDUCATION_SCOPE, FINANCE_SCOPE, LEGAL_SCOPE, LOGISTICS_SCOPE
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import (
    candidate_branch,
    constraint,
    ledger_event,
    obligation,
    outcome,
    recurring_commitment,
    scoped,
    source_document,
)
from ._fake_graph_reader import FakeGraphReader
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore
from ._gemini_fakes import FakeModels, fake_router

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_PIPELINE_PATH = _BACKEND_ROOT / "app" / "agents" / "council" / "pipeline.py"


def _shared_client(fake_models: FakeModels) -> GeminiClient:
    return GeminiClient(router=fake_router(fake_models))


class TestCarWorkedExample:
    """spec §12.4: repeated maintenance triggers a car decision. Finance,
    Logistics, and Care are convened (Care holds a real HARD mobility
    constraint that eliminates the SUV); delegates for Dad, Mum, and
    Grandma score the two surviving options in genuine conflict; the
    Adversary cites real household maintenance-underestimate history."""

    def test_full_car_pipeline_traces_to_real_fixture_facts(self) -> None:
        commitment = recurring_commitment("commitment-school-fees", label="School fees")
        repair_event = ledger_event("event-repair-1", amount=18000.0, counterparty_raw="City Auto Repairs")
        mobility_constraint = constraint(
            "constraint-dad-mobility",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.HARD,
            original_text="Dad cannot step up more than 45cm to enter a vehicle",
            structured={"max_door_sill_cm": "45"},
        )
        school_run = obligation("obligation-school-run", "School run", obligation_type="school")
        dialysis_trip = obligation("obligation-dialysis", "Dialysis trip", obligation_type="medical")
        maintenance_outcome = outcome(
            "outcome-maintenance",
            predicted="~₹20k/yr maintenance",
            actual="₹28k/yr maintenance",
            variance=0.4,
            attribution_tags=("major_purchase",),
        )

        related_ids = (
            "commitment-school-fees",
            "event-repair-1",
            "constraint-dad-mobility",
            "obligation-school-run",
            "obligation-dialysis",
        )
        hatchback = candidate_branch(
            "branch-hatchback",
            "Compact hatchback",
            "Low door sill 38cm, small boot",
            related_node_ids=related_ids,
        )
        suv = candidate_branch(
            "branch-suv", "SUV", "High door sill 55cm, large boot", related_node_ids=related_ids
        )
        crossover = candidate_branch(
            "branch-crossover", "Crossover", "Mid door sill 42cm, medium boot", related_node_ids=related_ids
        )

        reader = FakeGraphReader(
            nodes_by_id={
                "commitment-school-fees": commitment,
                "event-repair-1": repair_event,
                "constraint-dad-mobility": mobility_constraint,
                "obligation-school-run": school_run,
                "obligation-dialysis": dialysis_trip,
            },
            outcome_variance_by_tag={"major_purchase": (maintenance_outcome,)},
            history_by_entity={"branch-crossover": ()},
        )
        writer = FakeGraphWriter()

        fake_models = FakeModels(
            texts=[
                # 1. Convener
                json.dumps(
                    {
                        "convened_specialist_ids": ["A42", "A43", "A45"],
                        "convened_delegate_person_ids": ["person-dad", "person-mum", "person-grandma"],
                    }
                ),
                # 2. A42 Finance
                json.dumps(
                    {
                        "stance": "supports",
                        "reasoning": "Savings and the school-fee commitment leave room for either option.",
                        "evidence_refs": ["commitment-school-fees", "event-repair-1"],
                    }
                ),
                # 3. A43 Care — eliminates the SUV
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "The SUV's 55cm door sill exceeds Dad's real 45cm mobility limit.",
                        "evidence_refs": ["constraint-dad-mobility"],
                        "hard_eliminations": [
                            {"branch_id": "branch-suv", "reason": "exceeds max door sill height"}
                        ],
                    }
                ),
                # 4. A45 Logistics
                json.dumps(
                    {
                        "stance": "neutral",
                        "reasoning": "Both surviving options handle the school run and dialysis trip.",
                        "evidence_refs": ["obligation-school-run", "obligation-dialysis"],
                    }
                ),
                # 5. A47 for Dad
                json.dumps(
                    {
                        "reasoning": "Dad strongly prefers the lowest step-up for his own mobility.",
                        "branch_costs": [
                            {"branch_id": "branch-hatchback", "cost": 2.0, "confidence": 0.9},
                            {"branch_id": "branch-crossover", "cost": 5.0, "confidence": 0.9},
                        ],
                    }
                ),
                # 6. A47 for Mum
                json.dumps(
                    {
                        "reasoning": "Mum needs boot space for groceries and the school run.",
                        "branch_costs": [
                            {"branch_id": "branch-hatchback", "cost": 8.0, "confidence": 0.9},
                            {"branch_id": "branch-crossover", "cost": 3.0, "confidence": 0.9},
                        ],
                    }
                ),
                # 7. A47 for Grandma
                json.dumps(
                    {
                        "reasoning": "Grandma finds a mid-height seat easiest to get in and out of.",
                        "branch_costs": [
                            {"branch_id": "branch-hatchback", "cost": 6.0, "confidence": 0.9},
                            {"branch_id": "branch-crossover", "cost": 2.0, "confidence": 0.9},
                        ],
                    }
                ),
                # 8. A48 Adversary
                json.dumps(
                    {
                        "critique": "This household underestimated maintenance costs by 40% on its last "
                        "major purchase (outcome 0).",
                        "cited_evidence_indices": [0],
                    }
                ),
            ]
        )

        convener = CouncilConvenerAgent(
            gemini_client=_shared_client(fake_models),
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
        )
        specialists_by_id: dict[str, pipeline.SpecialistAgent] = {
            "A42": FinanceSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, FINANCE_SCOPE)
            ),
            "A43": CareSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, CARE_SCOPE)
            ),
            "A45": LogisticsSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, LOGISTICS_SCOPE)
            ),
        }
        delegates_by_person_id = {
            NodeId("person-dad"): MemberDelegateAgent(
                gemini_client=_shared_client(fake_models), person_id=NodeId("person-dad")
            ),
            NodeId("person-mum"): MemberDelegateAgent(
                gemini_client=_shared_client(fake_models), person_id=NodeId("person-mum")
            ),
            NodeId("person-grandma"): MemberDelegateAgent(
                gemini_client=_shared_client(fake_models), person_id=NodeId("person-grandma")
            ),
        }
        adversary = CouncilAdversaryAgent(gemini_client=_shared_client(fake_models), graph_reader=reader)
        recorder = CouncilRecorderAgent(graph_writer=writer, idempotency_store=InMemoryIdempotencyStore())

        participants = pipeline.CouncilParticipants(
            convener=convener,
            specialists_by_id=specialists_by_id,
            delegates_by_person_id=delegates_by_person_id,
            adversary=adversary,
            recorder=recorder,
        )
        convener_request = ConvenerRequest(
            question="Should we buy a new car?",
            trigger="repeated maintenance costs",
            household_members=(
                HouseholdMemberSummary(
                    person_id=NodeId("person-dad"),
                    display_name="Dad",
                    role="adult",
                    materially_affected_note=None,
                ),
                HouseholdMemberSummary(
                    person_id=NodeId("person-mum"),
                    display_name="Mum",
                    role="adult",
                    materially_affected_note=None,
                ),
                HouseholdMemberSummary(
                    person_id=NodeId("person-grandma"),
                    display_name="Grandma",
                    role="elder",
                    materially_affected_note="real mobility constraint on file",
                ),
            ),
        )

        brief = pipeline.run(
            participants=participants,
            convener_request=convener_request,
            candidate_branches=(hatchback, suv, crossover),
            category_tag="major_purchase",
            known_preference_signals_by_person_id={
                NodeId("person-dad"): ("historically prioritises low step-up entry",),
                NodeId("person-mum"): ("historically prioritises boot space",),
                NodeId("person-grandma"): ("historically prefers a mid-height seat",),
            },
            elicitation_method_by_person_id={
                NodeId("person-dad"): "observed_history",
                NodeId("person-mum"): "observed_history",
                NodeId("person-grandma"): "interview",
            },
            cycle_id="cycle-car-1",
        )

        # Real Care hard constraint eliminating a real branch.
        assert brief.resolution.eliminated_branch_ids == (NodeId("branch-suv"),)
        care_position = next(p for p in brief.specialist_positions if p.agent_id == "A43")
        assert care_position.eliminated_branch_ids == (NodeId("branch-suv"),)

        # Pipeline-level wiring removed the eliminated branch from delegate
        # scoring entirely — not merely from the arbiter's cost lookup.
        # Calls 5-7 (index 4-6) are the three delegates' own prompts; the
        # SUV must never even be mentioned in what they were shown.
        for delegate_call in fake_models.calls[4:7]:
            delegate_prompt = str(delegate_call["contents"])
            assert "branch-suv" not in delegate_prompt
            assert "SUV" not in delegate_prompt
        for scoring in brief.delegate_scorings:
            assert "branch-suv" not in scoring.valuation_profile.costs

        # Real, computed trade-off naming a real person.
        assert brief.resolution.winning_branch_id == NodeId("branch-crossover")
        assert brief.resolution.conceding_person_ids == (NodeId("person-dad"),)
        assert brief.resolution.regret_by_person[NodeId("person-dad")] == pytest.approx(3.0)

        # Real adversary citation.
        assert brief.adversary_attack.cited_outcome_ids == (NodeId("outcome-maintenance"),)
        assert brief.risk_register == (brief.adversary_attack.critique,)

        # Everything got recorded — 3 specialists + 3 delegates + 1 adversary = 7 positions.
        written_positions = [n for n in writer.nodes.values() if isinstance(n, CouncilPosition)]
        assert len(written_positions) == 7
        conceded_edges = [e for e in writer.edges if e.edge_type.value == "conceded_by"]
        assert len(conceded_edges) == 1
        assert conceded_edges[0].to_id == NodeId("person-dad")

    def test_all_branches_eliminated_raises_no_surviving_branches(self) -> None:
        mobility_constraint = constraint(
            "constraint-dad-mobility",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.HARD,
            original_text="Dad cannot step into any real candidate here",
        )
        only_branch = candidate_branch(
            "branch-suv", "SUV", "High door sill", related_node_ids=("constraint-dad-mobility",)
        )
        reader = FakeGraphReader(nodes_by_id={"constraint-dad-mobility": mobility_constraint})
        writer = FakeGraphWriter()
        fake_models = FakeModels(
            texts=[
                json.dumps(
                    {"convened_specialist_ids": ["A43"], "convened_delegate_person_ids": ["person-dad"]}
                ),
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "No surviving option fits.",
                        "evidence_refs": ["constraint-dad-mobility"],
                        "hard_eliminations": [{"branch_id": "branch-suv", "reason": "no fit"}],
                    }
                ),
            ]
        )
        convener = CouncilConvenerAgent(
            gemini_client=_shared_client(fake_models),
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
        )
        participants = pipeline.CouncilParticipants(
            convener=convener,
            specialists_by_id={
                "A43": CareSpecialistAgent(
                    gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, CARE_SCOPE)
                )
            },
            delegates_by_person_id={},
            adversary=CouncilAdversaryAgent(gemini_client=_shared_client(fake_models), graph_reader=reader),
            recorder=CouncilRecorderAgent(graph_writer=writer, idempotency_store=InMemoryIdempotencyStore()),
        )
        convener_request = ConvenerRequest(
            question="Buy a car?",
            trigger="repairs",
            household_members=(
                HouseholdMemberSummary(
                    person_id=NodeId("person-dad"),
                    display_name="Dad",
                    role="adult",
                    materially_affected_note=None,
                ),
            ),
        )

        with pytest.raises(NoSurvivingBranches):
            pipeline.run(
                participants=participants,
                convener_request=convener_request,
                candidate_branches=(only_branch,),
                category_tag="major_purchase",
                known_preference_signals_by_person_id={},
                elicitation_method_by_person_id={},
                cycle_id="cycle-car-2",
            )


class TestHouseWorkedExample:
    """spec §12.5: same protocol, wider blast radius. Finance, Education,
    Care, Logistics, and Legal are convened; Care's real HARD constraint
    (max distance to a specialist doctor) eliminates the distant suburb;
    two parent delegates score the two surviving options in genuine
    conflict; the Adversary cites real household relocation-cost history."""

    def test_full_house_pipeline_traces_to_real_fixture_facts(self) -> None:
        commitment = recurring_commitment("commitment-society-maintenance", label="Society maintenance")
        deposit_event = ledger_event(
            "event-deposit-1", amount=200000.0, counterparty_raw="New Society Escrow"
        )
        cardiologist_constraint = constraint(
            "constraint-cardiologist-distance",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.HARD,
            original_text="Elder's cardiologist visits require staying within 5km of the current clinic",
            structured={"max_distance_km": "5"},
        )
        board_exam_constraint = constraint(
            "constraint-board-exam",
            kind=ConstraintKind.EDUCATION,
            severity=ConstraintSeverity.SOFT,
            original_text="Child is in her board-exam year and should not change schools mid-year",
        )
        commute_obligation = obligation(
            "obligation-commute", "Daily office commute", obligation_type="commute"
        )
        society_rules = source_document("doc-society-rules", document_type="society_notice")
        relocation_outcome = outcome(
            "outcome-relocation-cost",
            predicted="Moving costs ~₹1L",
            actual="Moving costs ₹1.6L",
            variance=0.6,
            attribution_tags=("relocation",),
        )

        related_ids = (
            "commitment-society-maintenance",
            "event-deposit-1",
            "constraint-cardiologist-distance",
            "constraint-board-exam",
            "obligation-commute",
            "doc-society-rules",
        )
        stay = candidate_branch(
            "branch-stay", "Stay put", "Remain in the current flat", related_node_ids=related_ids
        )
        nearby_society = candidate_branch(
            "branch-nearby-society",
            "Move to nearby society",
            "2km from the cardiologist's clinic",
            related_node_ids=related_ids,
        )
        far_suburb = candidate_branch(
            "branch-far-suburb",
            "Move to a far suburb",
            "18km from the cardiologist's clinic",
            related_node_ids=related_ids,
        )

        reader = FakeGraphReader(
            nodes_by_id={
                "commitment-society-maintenance": commitment,
                "event-deposit-1": deposit_event,
                "constraint-cardiologist-distance": cardiologist_constraint,
                "constraint-board-exam": board_exam_constraint,
                "obligation-commute": commute_obligation,
                "doc-society-rules": society_rules,
            },
            outcome_variance_by_tag={"relocation": (relocation_outcome,)},
            history_by_entity={"branch-nearby-society": ()},
        )
        writer = FakeGraphWriter()

        fake_models = FakeModels(
            texts=[
                # 1. Convener
                json.dumps(
                    {
                        "convened_specialist_ids": ["A42", "A43", "A44", "A45", "A46"],
                        "convened_delegate_person_ids": ["person-parent1", "person-parent2"],
                    }
                ),
                # 2. A42 Finance
                json.dumps(
                    {
                        "stance": "neutral",
                        "reasoning": "The deposit and society maintenance are affordable either way.",
                        "evidence_refs": ["commitment-society-maintenance", "event-deposit-1"],
                    }
                ),
                # 3. A43 Care — eliminates the far suburb
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "The far suburb is 18km out, beyond the real 5km cardiologist limit.",
                        "evidence_refs": ["constraint-cardiologist-distance"],
                        "hard_eliminations": [
                            {"branch_id": "branch-far-suburb", "reason": "exceeds max distance to specialist"}
                        ],
                    }
                ),
                # 4. A44 Education
                json.dumps(
                    {
                        "stance": "opposes",
                        "reasoning": "Any move risks disrupting the child's board-exam year.",
                        "evidence_refs": ["constraint-board-exam"],
                    }
                ),
                # 5. A45 Logistics
                json.dumps(
                    {
                        "stance": "neutral",
                        "reasoning": "The nearby society has a comparable commute to the current flat.",
                        "evidence_refs": ["obligation-commute"],
                    }
                ),
                # 6. A46 Legal
                json.dumps(
                    {
                        "stance": "neutral",
                        "reasoning": "Society transfer rules require standard docs; flag for review.",
                        "evidence_refs": ["doc-society-rules"],
                    }
                ),
                # 7. A47 for parent1
                json.dumps(
                    {
                        "reasoning": "Parent1 strongly prefers not disrupting the household with a move.",
                        "branch_costs": [
                            {"branch_id": "branch-stay", "cost": 1.0, "confidence": 0.9},
                            {"branch_id": "branch-nearby-society", "cost": 4.0, "confidence": 0.9},
                        ],
                    }
                ),
                # 8. A47 for parent2
                json.dumps(
                    {
                        "reasoning": "Parent2 finds the current flat too cramped and prefers the move.",
                        "branch_costs": [
                            {"branch_id": "branch-stay", "cost": 5.0, "confidence": 0.9},
                            {"branch_id": "branch-nearby-society", "cost": 1.0, "confidence": 0.9},
                        ],
                    }
                ),
                # 9. A48 Adversary
                json.dumps(
                    {
                        "critique": "This household underestimated relocation costs by 60% last time "
                        "(outcome 0) — budget for real overruns.",
                        "cited_evidence_indices": [0],
                    }
                ),
            ]
        )

        convener = CouncilConvenerAgent(
            gemini_client=_shared_client(fake_models),
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
        )
        specialists_by_id: dict[str, pipeline.SpecialistAgent] = {
            "A42": FinanceSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, FINANCE_SCOPE)
            ),
            "A43": CareSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, CARE_SCOPE)
            ),
            "A44": EducationSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, EDUCATION_SCOPE)
            ),
            "A45": LogisticsSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, LOGISTICS_SCOPE)
            ),
            "A46": LegalSpecialistAgent(
                gemini_client=_shared_client(fake_models), scoped_reader=scoped(reader, LEGAL_SCOPE)
            ),
        }
        delegates_by_person_id = {
            NodeId("person-parent1"): MemberDelegateAgent(
                gemini_client=_shared_client(fake_models), person_id=NodeId("person-parent1")
            ),
            NodeId("person-parent2"): MemberDelegateAgent(
                gemini_client=_shared_client(fake_models), person_id=NodeId("person-parent2")
            ),
        }
        adversary = CouncilAdversaryAgent(gemini_client=_shared_client(fake_models), graph_reader=reader)
        recorder = CouncilRecorderAgent(graph_writer=writer, idempotency_store=InMemoryIdempotencyStore())

        participants = pipeline.CouncilParticipants(
            convener=convener,
            specialists_by_id=specialists_by_id,
            delegates_by_person_id=delegates_by_person_id,
            adversary=adversary,
            recorder=recorder,
        )
        convener_request = ConvenerRequest(
            question="Should we move to the new society flat?",
            trigger="lease renewal notice",
            household_members=(
                HouseholdMemberSummary(
                    person_id=NodeId("person-parent1"),
                    display_name="Parent1",
                    role="adult",
                    materially_affected_note=None,
                ),
                HouseholdMemberSummary(
                    person_id=NodeId("person-parent2"),
                    display_name="Parent2",
                    role="adult",
                    materially_affected_note=None,
                ),
            ),
        )

        brief = pipeline.run(
            participants=participants,
            convener_request=convener_request,
            candidate_branches=(stay, nearby_society, far_suburb),
            category_tag="relocation",
            known_preference_signals_by_person_id={
                NodeId("person-parent1"): ("historically averse to moving",),
                NodeId("person-parent2"): ("historically wants more space",),
            },
            elicitation_method_by_person_id={
                NodeId("person-parent1"): "observed_history",
                NodeId("person-parent2"): "observed_history",
            },
            cycle_id="cycle-house-1",
        )

        # Real Care hard constraint eliminating a real branch.
        assert brief.resolution.eliminated_branch_ids == (NodeId("branch-far-suburb"),)
        care_position = next(p for p in brief.specialist_positions if p.agent_id == "A43")
        assert care_position.eliminated_branch_ids == (NodeId("branch-far-suburb"),)
        assert {p.agent_id for p in brief.specialist_positions} == {"A42", "A43", "A44", "A45", "A46"}

        # Pipeline-level wiring removed the eliminated branch from delegate
        # scoring entirely. Calls 7-8 (index 6-7) are the two delegates'
        # own prompts, after the convener (0) and five specialists (1-5).
        for delegate_call in fake_models.calls[6:8]:
            delegate_prompt = str(delegate_call["contents"])
            assert "branch-far-suburb" not in delegate_prompt
            assert "far suburb" not in delegate_prompt.lower()
        for scoring in brief.delegate_scorings:
            assert "branch-far-suburb" not in scoring.valuation_profile.costs

        # Real, computed trade-off naming a real person.
        assert brief.resolution.winning_branch_id == NodeId("branch-nearby-society")
        assert brief.resolution.conceding_person_ids == (NodeId("person-parent1"),)

        # Real adversary citation, distinct category from the car example.
        assert brief.adversary_attack.cited_outcome_ids == (NodeId("outcome-relocation-cost"),)

        written_positions = [n for n in writer.nodes.values() if isinstance(n, CouncilPosition)]
        assert len(written_positions) == 8  # 5 specialists + 2 delegates + 1 adversary


class TestSpecialistIsolationIsStructural:
    """Spec §12.3 Phase 1: "before seeing any other agent's output."
    Structural, AST-based proof that `pipeline.py`'s own specialist-
    reporting loop never references its own results-accumulator when
    building a `SpecialistReportRequest` for the next call — isolation is
    true of how this file is *written*, not merely of what it happened to
    do this run."""

    def test_specialist_report_request_construction_never_references_the_accumulator(self) -> None:
        tree = ast.parse(_PIPELINE_PATH.read_text(encoding="utf-8"), filename=str(_PIPELINE_PATH))
        forbidden_names = {"specialist_positions", "specialist_positions_tuple", "delegate_scorings"}
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "SpecialistReportRequest"
            ):
                referenced = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                overlap = referenced & forbidden_names
                assert overlap == set(), (
                    f"SpecialistReportRequest construction must never reference {overlap} "
                    "(Phase-1 isolation must be structural, not incidental)"
                )
