"""Tests for `app.arbitration.confidence_arbiter.ConfidenceArbiter` — A57,
"the only path to action" (spec §15.12).

**Cross-role wiring note:** a real Pro-tier borderline call requires
`AgentId("A57")` on `app.reasoning.model_router.PRO_TIER_ALLOWLIST` — that
module is E2-owned (`backend/app/reasoning/`) and this phase's E3 work does
not edit it (file ownership, PHASES.md Appendix D rule 3). Tests that
exercise the real borderline path `monkeypatch` the allowlist for the
duration of the test only (a standard, non-invasive pytest technique — the
source file itself is never modified) so this module's *own* decision
logic is proven correct in isolation from that separately-tracked gap. See
this phase's final report for the exact one-line change E2/the CTO need to
land in production.
"""

from __future__ import annotations

import json

import pytest
from contracts.actions import RiskTier
from contracts.graph_types import AgentId, NodeId

from app.arbitration.confidence_arbiter import AGENT_ID, ConfidenceArbiter
from app.arbitration.types import ArbiterDecision, ProposedAction
from app.reasoning import model_router as model_router_module
from app.reasoning.errors import ActionTypeNotClassified
from app.reasoning.gemini_client import GeminiClient
from app.reasoning.risk_policy import ActionTypes

from ._gemini_fakes import FakeModels, FakeResponse, fake_router


@pytest.fixture(autouse=True)
def _allow_a57_pro_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patches the real allowlist (module attribute, not the source file)
    so `ModelRouter.route()`'s live lookup sees `AGENT_ID` as allowlisted
    for the duration of each test — see module docstring."""
    monkeypatch.setattr(
        model_router_module, "PRO_TIER_ALLOWLIST", model_router_module.PRO_TIER_ALLOWLIST | {AGENT_ID}
    )


def _proposed(
    *,
    action_type: str = ActionTypes.PAY_DUES,
    confidence: float = 0.95,
    involves_hard_constraint: bool = False,
) -> ProposedAction:
    return ProposedAction(
        action_type=action_type,
        entity_id="due-1",
        cycle="2026-08",
        target_node_id=NodeId("ledger-event-1"),
        confidence=confidence,
        involves_hard_constraint=involves_hard_constraint,
        reasoning="Monthly society dues, matches last month's amount within tolerance.",
        evidence_consulted=("receipt:doc-1", "recurring_commitment:dues-society"),
        consequence_if_wrong="A duplicate or incorrect debit from the household account.",
        proposed_by=AgentId("A27"),
        source_ref=None,
    )


def _arbiter_with_response(*responses: dict[str, object]) -> ConfidenceArbiter:
    fake_models = FakeModels(texts=[json.dumps(r) for r in responses] or ["{}"])
    client = GeminiClient(router=fake_router(fake_models))
    return ConfidenceArbiter(gemini_client=client)


def _arbiter_never_calling_model() -> ConfidenceArbiter:
    """A `GeminiClient` whose underlying call would raise if ever invoked —
    used to prove the clearly-above/clearly-below paths never call the
    model at all (cost discipline)."""

    class _ExplodingModels(FakeModels):
        def generate_content(self, *, model: str, contents: object, config: object = None) -> FakeResponse:
            raise AssertionError(
                "Pro-tier model call made for a non-borderline case — cost discipline violated"
            )

    fake_models = _ExplodingModels(texts=["{}"])
    client = GeminiClient(router=fake_router(fake_models))
    return ConfidenceArbiter(gemini_client=client)


class TestClearCutExecute:
    def test_high_confidence_r0_action_executes_without_a_model_call(self) -> None:
        arbiter = _arbiter_never_calling_model()
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.GRAPH_WRITE, confidence=0.99))
        assert result.decision is ArbiterDecision.EXECUTE
        assert result.final_risk_tier is RiskTier.R0_SILENT
        assert result.escalated_to_pro is False

    def test_high_confidence_r3_action_routes_to_approve(self) -> None:
        arbiter = _arbiter_never_calling_model()
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.PAY_DUES, confidence=0.95))
        assert result.decision is ArbiterDecision.APPROVE
        assert result.final_risk_tier is RiskTier.R3_EXPLICIT_APPROVE

    def test_r4_action_always_escalates(self) -> None:
        arbiter = _arbiter_never_calling_model()
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.RELOCATION, confidence=0.99))
        assert result.decision is ArbiterDecision.ESCALATE
        assert result.final_risk_tier is RiskTier.R4_ESCALATE_ONLY


class TestHardConstraintFloor:
    def test_hard_constraint_forces_at_least_r2(self) -> None:
        arbiter = _arbiter_never_calling_model()
        result = arbiter.evaluate(
            _proposed(action_type=ActionTypes.GRAPH_WRITE, confidence=0.9, involves_hard_constraint=True)
        )
        assert result.final_risk_tier is RiskTier.R2_APPROVE
        assert result.decision is ArbiterDecision.APPROVE


class TestClearlyBelowFloorDowngrades:
    def test_clearly_low_confidence_downgrades_at_least_one_tier_without_a_model_call(self) -> None:
        arbiter = _arbiter_never_calling_model()
        # R2's floor is 0.75; 0.40 is far below (not borderline).
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.SEND_MESSAGE_EXTERNAL, confidence=0.40))
        assert result.escalated_to_pro is False
        assert result.final_risk_tier is RiskTier.R3_EXPLICIT_APPROVE  # downgraded one step stricter than R2
        assert result.decision is ArbiterDecision.APPROVE

    def test_clearly_low_confidence_at_r4_discards_rather_than_downgrading(self) -> None:
        arbiter = _arbiter_never_calling_model()
        # R4's floor is 0.92; 0.5 is far below.
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.MEDICAL_CHOICE, confidence=0.5))
        assert result.decision is ArbiterDecision.DISCARD
        assert result.discard_reason is not None
        assert "R4" in result.discard_reason


class TestAbsoluteDiscardFloor:
    def test_catastrophically_low_confidence_is_discarded_regardless_of_tier(self) -> None:
        arbiter = _arbiter_never_calling_model()
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.GRAPH_WRITE, confidence=0.05))
        assert result.decision is ArbiterDecision.DISCARD
        assert result.escalated_to_pro is False


class TestBorderlinePromptsProTier:
    def test_borderline_confidence_calls_pro_tier_and_proceed_true_keeps_tier(self) -> None:
        # R3's floor is 0.88; 0.86 is within the 0.05 borderline band.
        arbiter = _arbiter_with_response(
            {"proceed": True, "explanation": "well-corroborated by two receipts"}
        )
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.PAY_DUES, confidence=0.86))
        assert result.escalated_to_pro is True
        assert result.decision is ArbiterDecision.APPROVE
        assert result.final_risk_tier is RiskTier.R3_EXPLICIT_APPROVE

    def test_borderline_confidence_proceed_false_downgrades(self) -> None:
        arbiter = _arbiter_with_response({"proceed": False, "explanation": "evidence is thin"})
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.PAY_DUES, confidence=0.86))
        assert result.escalated_to_pro is True
        assert result.final_risk_tier is RiskTier.R4_ESCALATE_ONLY
        assert result.decision is ArbiterDecision.ESCALATE

    def test_malformed_borderline_response_never_silently_proceeds(self) -> None:
        arbiter = _arbiter_with_response({"not_the_expected_shape": True})
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.PAY_DUES, confidence=0.86))
        assert result.escalated_to_pro is True
        # malformed -> treated as False (never a silent "proceed")
        assert result.final_risk_tier is RiskTier.R4_ESCALATE_ONLY


class TestUnmappedActionTypePropagates:
    def test_unmapped_action_type_raises_rather_than_guessing(self) -> None:
        arbiter = _arbiter_never_calling_model()
        with pytest.raises(ActionTypeNotClassified):
            arbiter.evaluate(_proposed(action_type="totally_unregistered_action_type"))


class TestOnlyPathToActionDoesNotConstructActions:
    def test_evaluate_never_returns_an_action_object(self) -> None:
        """`ArbiterResult` carries data only — no `contracts.actions.Action`
        instance. Constructing one is the Approval Gate's job (for
        APPROVE) or an R0/R1 executor's (for EXECUTE), both living in
        `app.arbitration`, never here."""
        arbiter = _arbiter_never_calling_model()
        result = arbiter.evaluate(_proposed(action_type=ActionTypes.GRAPH_WRITE, confidence=0.99))
        assert not hasattr(result, "execute")
