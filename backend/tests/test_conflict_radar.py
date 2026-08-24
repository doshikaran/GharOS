"""Tests for A14 Conflict Radar (`app.agents.consequence.conflict_radar`).

PHASES.md Gate 4: "Temporal collision (1:30 pickup vs 1:00 meeting)
detected" — the deterministic-layer test below deliberately reuses E1's
own fixture shape from `test_conflict_prepass.py`
(`test_field_trip_pickup_vs_work_meeting_detected`) rather than inventing
a divergent one, per the resume brief's explicit instruction.

Forbidden: unilaterally resolving a multi-person conflict — proven
structurally (`ConflictFinding` has no resolution field) and by a direct
test on the reasoning-layer output shape.

Uses the real Firestore emulator (`reader`/`writer` fixtures) throughout,
even for reasoning-layer-only tests, so `DeterministicConflictPrepass`
never needs a hand-rolled test double for `GraphReader`.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

from contracts.agents import Citation
from contracts.graph_types import (
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
)

from app.agents.consequence.conflict_radar import AGENT_ID, ConflictRadar
from app.agents.consequence.types import ConflictFinding, HouseholdContext, ImpliedObligationCandidate
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.reasoning.gemini_client import GeminiClient
from app.solvers.conflict_prepass import DeterministicConflictPrepass
from tests.conftest import NOW, make_person, make_provenance

from ._gemini_fakes import FakeModels, fake_router

_WIDE_WINDOW = (NOW - timedelta(days=1), NOW + timedelta(days=1))
_HIGH_THRESHOLD_MINUTES = 10_000.0


def _obligation(
    node_id: str, title: str, *, due_at: datetime | None, effort_estimate_minutes: int | None
) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=make_provenance(),
        title=title,
        obligation_type="errand",
        due_at=due_at,
        must_start_by=None,
        effort_estimate_minutes=effort_estimate_minutes,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _own(writer: FirestoreGraphWriter, edge_id: str, obligation_id: NodeId, person_id: NodeId) -> None:
    writer.write_edge(
        Edge(
            id=EdgeId(edge_id),
            provenance=make_provenance(),
            edge_type=EdgeType.OWNED_BY,
            from_id=obligation_id,
            to_id=person_id,
        )
    )


def _never_called_client() -> GeminiClient:
    """A `GeminiClient` whose underlying fake raises if actually invoked
    — used to prove no Pro-tier call happens when it shouldn't (cost
    discipline): either `candidates` is empty, or the deterministic layer
    alone already answers the test."""
    fake_models = FakeModels(texts=["SHOULD NEVER BE CALLED"], error=AssertionError("unexpected Gemini call"))
    return GeminiClient(router=fake_router(fake_models))


def _candidate(
    candidate_id: str, title: str, *, due_at: datetime | None = None
) -> ImpliedObligationCandidate:
    return ImpliedObligationCandidate(
        candidate_id=candidate_id,
        title=title,
        obligation_type="errand",
        due_at=due_at,
        effort_estimate_minutes=15,
        reasoning="test reasoning",
        citation=Citation(source_document_id="doc-1", region="0-5", supports_claim=title),
        cited_span_text="stub",
        confidence=0.8,
    )


class TestDeterministicLayerReusesE1Fixture:
    def test_field_trip_pickup_vs_work_meeting_detected_via_conflict_radar(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = make_person("person-priya-radar", "Priya")
        writer.write_node(priya)

        meeting = _obligation(
            "obligation-radar-meeting",
            "1:00pm work meeting",
            due_at=NOW.replace(hour=14, minute=0),
            effort_estimate_minutes=60,
        )
        pickup = _obligation(
            "obligation-radar-pickup",
            "Early pickup - field trip",
            due_at=NOW.replace(hour=13, minute=30),
            effort_estimate_minutes=15,
        )
        writer.write_node(meeting)
        writer.write_node(pickup)
        _own(writer, "e-radar-own-meeting", meeting.id, priya.id)
        _own(writer, "e-radar-own-pickup", pickup.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        radar = ConflictRadar(gemini_client=_never_called_client(), prepass=prepass)

        context = HouseholdContext(
            people=(priya,), constraints=(), open_obligations=(pickup,), stated_obligations=(meeting,)
        )
        findings = radar.detect(
            candidates=(),
            household_context=context,
            fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES,
            load_window=_WIDE_WINDOW,
        )

        temporal_findings = [f for f in findings if f.kind == "temporal"]
        assert len(temporal_findings) == 1
        finding = temporal_findings[0]
        assert finding.from_deterministic_prepass is True
        assert finding.confidence == 1.0
        assert {finding.subject_candidate_id, finding.other_id} == {str(meeting.id), str(pickup.id)}

    def test_no_candidates_and_no_graph_obligations_makes_no_llm_call(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        prepass = DeterministicConflictPrepass(reader)
        radar = ConflictRadar(gemini_client=_never_called_client(), prepass=prepass)
        context = HouseholdContext(people=(), constraints=(), open_obligations=(), stated_obligations=())
        findings = radar.detect(
            candidates=(),
            household_context=context,
            fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES,
            load_window=_WIDE_WINDOW,
        )
        assert findings == ()


class TestReasoningLayerForNewCandidates:
    def test_reasoning_layer_reports_a_conflict_between_two_new_candidates(
        self, reader: FirestoreGraphReader
    ) -> None:
        response = {
            "conflicts": [
                {
                    "kind": "temporal",
                    "subject_id": "candidate-a",
                    "other_reference": "candidate-b",
                    "explanation": "Both need the same person at the same time.",
                    "confidence": 0.8,
                }
            ]
        }
        fake_models = FakeModels(texts=[json.dumps(response)])
        radar = ConflictRadar(
            gemini_client=GeminiClient(router=fake_router(fake_models)),
            prepass=DeterministicConflictPrepass(reader),
        )
        context = HouseholdContext(people=(), constraints=(), open_obligations=(), stated_obligations=())

        findings = radar.detect(
            candidates=(_candidate("candidate-a", "Task A"), _candidate("candidate-b", "Task B")),
            household_context=context,
            fairness_threshold_minutes=10_000.0,
            load_window=_WIDE_WINDOW,
        )

        reasoning_findings = [f for f in findings if not f.from_deterministic_prepass]
        assert len(reasoning_findings) == 1
        assert reasoning_findings[0].kind == "temporal"
        assert reasoning_findings[0].subject_candidate_id == "candidate-a"
        assert reasoning_findings[0].other_id == "candidate-b"

    def test_no_candidates_skips_the_reasoning_call_entirely(
        self, reader: FirestoreGraphReader
    ) -> None:
        radar = ConflictRadar(
            gemini_client=_never_called_client(), prepass=DeterministicConflictPrepass(reader)
        )
        context = HouseholdContext(people=(), constraints=(), open_obligations=(), stated_obligations=())
        findings = radar.detect(
            candidates=(),
            household_context=context,
            fairness_threshold_minutes=10_000.0,
            load_window=_WIDE_WINDOW,
        )
        assert findings == ()

    def test_unknown_conflict_kind_from_model_is_dropped_not_crashed(
        self, reader: FirestoreGraphReader
    ) -> None:
        response = {
            "conflicts": [
                {
                    "kind": "not-a-real-kind",
                    "subject_id": "candidate-a",
                    "other_reference": "candidate-b",
                    "explanation": "x",
                    "confidence": 0.5,
                }
            ]
        }
        fake_models = FakeModels(texts=[json.dumps(response)])
        radar = ConflictRadar(
            gemini_client=GeminiClient(router=fake_router(fake_models)),
            prepass=DeterministicConflictPrepass(reader),
        )
        context = HouseholdContext(people=(), constraints=(), open_obligations=(), stated_obligations=())
        findings = radar.detect(
            candidates=(_candidate("candidate-a", "Task A"),),
            household_context=context,
            fairness_threshold_minutes=10_000.0,
            load_window=_WIDE_WINDOW,
        )
        assert findings == ()


class TestNeverResolvesConflicts:
    def test_conflict_finding_has_no_resolution_field(self) -> None:
        field_names = {f.name for f in ConflictFinding.__dataclass_fields__.values()}
        assert "resolution" not in field_names
        assert "chosen_option" not in field_names


class TestModelTierAllowlisted:
    def test_agent_id_on_pro_tier_allowlist(self) -> None:
        from app.reasoning.model_router import PRO_TIER_ALLOWLIST

        assert AGENT_ID in PRO_TIER_ALLOWLIST
