"""Tests for A13 Constraint Checker (`app.agents.consequence.constraint_checker`).

spec §15.4 A13, PHASES.md Gate 4: "Hard-constraint violation (nut allergy
vs planned lunch) detected"; forbidden: resolving violations; failure:
"hard-constraint ambiguity always escalates."
"""

from __future__ import annotations

import json

import pytest
from contracts.agents import Citation
from contracts.errors import EscalationRequired
from contracts.graph_types import Constraint, ConstraintKind, ConstraintSeverity, NodeId

from app.agents.consequence.constraint_checker import AGENT_ID, ConstraintCheckAgent
from app.agents.consequence.types import ImpliedObligationCandidate
from app.reasoning.gemini_client import GeminiClient
from tests.conftest import make_provenance

from ._gemini_fakes import FakeModels, fake_router


def _candidate(
    *, title: str = "Tuesday lunch: peanut butter sandwich", obligation_type: str = "menu"
) -> ImpliedObligationCandidate:
    return ImpliedObligationCandidate(
        candidate_id="candidate-lunch-1",
        title=title,
        obligation_type=obligation_type,
        due_at=None,
        effort_estimate_minutes=None,
        reasoning="Planned lunch for Tuesday.",
        citation=Citation(source_document_id="doc-1", region="0-10", supports_claim=title),
        cited_span_text="peanut butter sandwich",
        confidence=0.8,
    )


def _agent(*response_texts: dict[str, object]) -> ConstraintCheckAgent:
    fake_models = FakeModels(texts=[json.dumps(r) for r in response_texts])
    client = GeminiClient(router=fake_router(fake_models))
    return ConstraintCheckAgent(gemini_client=client)


def _constraint_with_provenance() -> Constraint:
    return Constraint(
        id=NodeId("constraint-nut-allergy"),
        provenance=make_provenance(),
        kind=ConstraintKind.DIETARY,
        severity=ConstraintSeverity.HARD,
        validity_start=None,
        validity_end=None,
        structured={"allergen": "nut"},
        original_text="Aarav has a severe nut allergy — no nuts, ever, including traces.",
    )


class TestHardConstraintViolationDetected:
    def test_nut_allergy_vs_peanut_butter_lunch_detected(self) -> None:
        constraint = _constraint_with_provenance()
        agent = _agent(
            {"verdict": "violates", "confidence": 0.97, "explanation": "Peanut butter contains nuts."}
        )

        findings = agent.check(candidate=_candidate(), constraints=(constraint,))

        assert len(findings) == 1
        finding = findings[0]
        assert finding.violates is True
        assert finding.constraint_id == constraint.id
        assert finding.severity is ConstraintSeverity.HARD
        assert finding.escalated_to_pro is False  # high-confidence Flash verdict, no escalation needed

    def test_no_violation_reported_when_flash_is_confident_and_clear(self) -> None:
        constraint = _constraint_with_provenance()
        agent = _agent(
            {"verdict": "no_violation", "confidence": 0.95, "explanation": "No allergens present."}
        )
        findings = agent.check(
            candidate=_candidate(title="Tuesday lunch: rice and dal"), constraints=(constraint,)
        )
        assert findings[0].violates is False


class TestHardConstraintAmbiguityEscalates:
    def test_ambiguous_flash_verdict_escalates_to_pro(self) -> None:
        constraint = _constraint_with_provenance()
        agent = _agent(
            {"verdict": "ambiguous", "confidence": 0.4, "explanation": "Unclear from the label alone."},
            {"verdict": "violates", "confidence": 0.9, "explanation": "Confirmed via ingredient list."},
        )
        findings = agent.check(candidate=_candidate(), constraints=(constraint,))
        assert findings[0].escalated_to_pro is True
        assert findings[0].violates is True

    def test_low_confidence_flash_on_hard_constraint_forces_escalation_even_if_clear(self) -> None:
        """Mirrors A5's hard-constraint-bearing pattern: a HARD
        constraint's Flash verdict is never trusted alone below the
        confidence floor, even if the verdict itself is not ambiguous."""
        constraint = _constraint_with_provenance()
        agent = _agent(
            {"verdict": "no_violation", "confidence": 0.5, "explanation": "Probably fine."},
            {"verdict": "no_violation", "confidence": 0.93, "explanation": "Confirmed safe on review."},
        )
        findings = agent.check(candidate=_candidate(), constraints=(constraint,))
        assert findings[0].escalated_to_pro is True

    def test_still_ambiguous_after_pro_escalation_raises_never_returns_a_finding(self) -> None:
        constraint = _constraint_with_provenance()
        agent = _agent(
            {"verdict": "ambiguous", "confidence": 0.3, "explanation": "Cannot tell from the label."},
            {"verdict": "ambiguous", "confidence": 0.35, "explanation": "Still cannot tell."},
        )
        with pytest.raises(EscalationRequired) as exc_info:
            agent.check(candidate=_candidate(), constraints=(constraint,))
        assert "constraint_id" in exc_info.value.context
        assert exc_info.value.context["candidate_id"] == "candidate-lunch-1"

    def test_soft_constraint_still_ambiguous_after_escalation_never_raises(self) -> None:
        """An ambiguous verdict escalates to Pro-tier regardless of
        severity (a genuine second opinion is always worth trying) — but
        only a HARD constraint's *still*-ambiguous-after-escalation result
        raises. A SOFT constraint's is returned as a real, honest,
        non-violating, low-confidence finding instead of a hard failure."""
        soft_constraint = Constraint(
            id=NodeId("constraint-soft-1"),
            provenance=make_provenance(),
            kind=ConstraintKind.SCHEDULE,
            severity=ConstraintSeverity.SOFT,
            validity_start=None,
            validity_end=None,
            structured={},
            original_text="We prefer to eat dinner before 8pm on weekdays.",
        )
        agent = _agent(
            {"verdict": "ambiguous", "confidence": 0.4, "explanation": "Timing unclear."},
            {"verdict": "ambiguous", "confidence": 0.45, "explanation": "Still unclear after review."},
        )
        findings = agent.check(
            candidate=_candidate(title="Dinner plan for weekday", obligation_type="menu"),
            constraints=(soft_constraint,),
        )
        assert len(findings) == 1
        assert findings[0].violates is False
        assert findings[0].escalated_to_pro is True


class TestNeverResolvesViolations:
    def test_finding_carries_no_resolution_field(self) -> None:
        """Structural: `ConstraintCheckFinding` has no field for a
        proposed fix — this test documents and pins that shape."""
        constraint = _constraint_with_provenance()
        agent = _agent({"verdict": "violates", "confidence": 0.9, "explanation": "Contains nuts."})
        finding = agent.check(candidate=_candidate(), constraints=(constraint,))[0]
        field_names = {f.name for f in finding.__dataclass_fields__.values()}
        assert "resolution" not in field_names
        assert "fix" not in field_names
        assert "suggested_substitution" not in field_names


class TestRelevancePrefilter:
    def test_soft_constraint_with_no_textual_overlap_is_skipped_without_a_call(self) -> None:
        unrelated_soft = Constraint(
            id=NodeId("constraint-unrelated"),
            provenance=make_provenance(),
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.SOFT,
            validity_start=None,
            validity_end=None,
            structured={"note": "wheelchair accessible entrance preferred"},
            original_text="Grandmother needs wheelchair-accessible venues for outings.",
        )
        fake_models = FakeModels(texts=[json.dumps({"ok": True})])
        client = GeminiClient(router=fake_router(fake_models))
        agent = ConstraintCheckAgent(gemini_client=client)

        findings = agent.check(
            candidate=_candidate(title="Buy stationery for school project", obligation_type="errand"),
            constraints=(unrelated_soft,),
        )
        assert findings == ()
        assert fake_models.calls == []  # no LLM call was made at all

    def test_hard_constraint_is_never_skipped_by_the_prefilter(self) -> None:
        unrelated_hard = Constraint(
            id=NodeId("constraint-hard-unrelated"),
            provenance=make_provenance(),
            kind=ConstraintKind.LEGAL,
            severity=ConstraintSeverity.HARD,
            validity_start=None,
            validity_end=None,
            structured={},
            original_text="Custody agreement requires both parents' written consent for travel abroad.",
        )
        agent = _agent({"verdict": "no_violation", "confidence": 0.9, "explanation": "Unrelated."})
        findings = agent.check(
            candidate=_candidate(title="Buy stationery for school project", obligation_type="errand"),
            constraints=(unrelated_hard,),
        )
        assert len(findings) == 1  # the model WAS called, despite zero textual overlap


class TestModelTierIsAllowlisted:
    def test_agent_id_on_pro_tier_allowlist(self) -> None:
        from app.reasoning.model_router import PRO_TIER_ALLOWLIST

        assert AGENT_ID in PRO_TIER_ALLOWLIST

    def test_flash_tier_used_first(self) -> None:
        constraint = _constraint_with_provenance()
        response = {"verdict": "violates", "confidence": 0.9, "explanation": "x"}
        fake_models = FakeModels(texts=[json.dumps(response)])
        client = GeminiClient(router=fake_router(fake_models))
        agent = ConstraintCheckAgent(gemini_client=client)
        agent.check(candidate=_candidate(), constraints=(constraint,))
        assert fake_models.calls[0]["model"] == "gemini-2.5-flash"
