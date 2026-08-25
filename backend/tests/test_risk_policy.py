"""Tests for `app.reasoning.risk_policy` — risk-tier classification per
action type and per-tier confidence floors.

PHASES.md Phase 5, "Work — E2": "Standardised confidence scoring;
risk-tier classification per action type." This is that work item's test
suite: every classification decision in `_ACTION_TYPE_RISK_TIER`, every
confidence-floor value, the unmapped-action-type failure path, and the
hard-constraint floor rule (spec §18.2 rule 2) are each proven directly,
in the parametrized style `test_model_router.py` uses for its allowlist
table.
"""

from __future__ import annotations

import pytest
from contracts.actions import RiskTier

from app.reasoning.errors import ActionTypeNotClassified
from app.reasoning.risk_policy import (
    ActionTypes,
    apply_hard_constraint_floor,
    classify_risk_tier,
    confidence_floor,
)

# ---------------------------------------------------------------------------
# classify_risk_tier — the full classification table, driven directly off
# spec §18.1's worked examples and the roster agents grounding each entry.
# ---------------------------------------------------------------------------

_EXPECTED_CLASSIFICATIONS: tuple[tuple[str, RiskTier], ...] = (
    # R0 — Silent
    (ActionTypes.GRAPH_WRITE, RiskTier.R0_SILENT),
    (ActionTypes.CALENDAR_ENTRY, RiskTier.R0_SILENT),
    (ActionTypes.INFORMATION_PREP, RiskTier.R0_SILENT),
    (ActionTypes.GRAPH_MAINTENANCE, RiskTier.R0_SILENT),
    # R1 — Notify
    (ActionTypes.DRAFT_MESSAGE, RiskTier.R1_NOTIFY),
    (ActionTypes.PROPOSE_MENU_SUBSTITUTION, RiskTier.R1_NOTIFY),
    (ActionTypes.SHOPPING_LIST, RiskTier.R1_NOTIFY),
    (ActionTypes.RENEGOTIATION_PROPOSAL, RiskTier.R1_NOTIFY),
    (ActionTypes.ESCALATION_WITH_OPTIONS, RiskTier.R1_NOTIFY),
    # R2 — Approve
    (ActionTypes.SEND_MESSAGE_EXTERNAL, RiskTier.R2_APPROVE),
    (ActionTypes.SUBMIT_FORM, RiskTier.R2_APPROVE),
    (ActionTypes.PLACE_CALL, RiskTier.R2_APPROVE),
    (ActionTypes.CANCEL_SUBSCRIPTION, RiskTier.R2_APPROVE),
    # R3 — Explicit approve
    (ActionTypes.PAY_DUES, RiskTier.R3_EXPLICIT_APPROVE),
    (ActionTypes.PAY_SALARY, RiskTier.R3_EXPLICIT_APPROVE),
    (ActionTypes.CANCEL_MANDATE, RiskTier.R3_EXPLICIT_APPROVE),
    (ActionTypes.FILE_DISPUTE, RiskTier.R3_EXPLICIT_APPROVE),
    # R4 — Escalate only
    (ActionTypes.RELOCATION, RiskTier.R4_ESCALATE_ONLY),
    (ActionTypes.PROPERTY_PURCHASE, RiskTier.R4_ESCALATE_ONLY),
    (ActionTypes.CARE_ARRANGEMENT, RiskTier.R4_ESCALATE_ONLY),
    (ActionTypes.END_STAFF_EMPLOYMENT, RiskTier.R4_ESCALATE_ONLY),
    (ActionTypes.MEDICAL_CHOICE, RiskTier.R4_ESCALATE_ONLY),
)


class TestClassifyRiskTier:
    @pytest.mark.parametrize(
        "action_type,expected_tier",
        _EXPECTED_CLASSIFICATIONS,
        ids=[action_type for action_type, _ in _EXPECTED_CLASSIFICATIONS],
    )
    def test_classification_table(self, action_type: str, expected_tier: RiskTier) -> None:
        assert classify_risk_tier(action_type) is expected_tier

    def test_every_action_types_constant_is_classified(self) -> None:
        """Tripwire against a constant added to `ActionTypes` without a
        corresponding table entry — the same drift `test_model_router.py`
        guards against by deriving its parametrization from the live
        allowlist rather than a hand-copied list."""
        constants = {
            value
            for name, value in vars(ActionTypes).items()
            if not name.startswith("_") and isinstance(value, str)
        }
        classified = {action_type for action_type, _ in _EXPECTED_CLASSIFICATIONS}
        assert constants == classified

    def test_unmapped_action_type_raises_action_type_not_classified(self) -> None:
        """spec §19.2: 'never silently proceed.' An action type with no
        classification must not resolve to R0/R1 (or any tier at all) —
        it must interrupt the caller."""
        with pytest.raises(ActionTypeNotClassified) as exc_info:
            classify_risk_tier("some_action_type_nobody_has_registered")

        assert exc_info.value.action_type == "some_action_type_nobody_has_registered"

    def test_unmapped_action_type_never_resolves_to_a_permissive_default(self) -> None:
        """Belt-and-braces on the same rule: assert the failure mode is
        genuinely 'raise', not 'return something' — a caller who forgot
        to `pytest.raises` would otherwise silently observe `None` or a
        falsy tier and might mistake that for R0."""
        with pytest.raises(ActionTypeNotClassified):
            result = classify_risk_tier("totally_unknown")
            # Unreachable if the contract holds — documents intent.
            assert result not in (RiskTier.R0_SILENT, RiskTier.R1_NOTIFY)

    def test_empty_string_action_type_raises(self) -> None:
        with pytest.raises(ActionTypeNotClassified):
            classify_risk_tier("")


# ---------------------------------------------------------------------------
# confidence_floor — distinct, strictly increasing per tier.
# ---------------------------------------------------------------------------

_EXPECTED_FLOORS: dict[RiskTier, float] = {
    RiskTier.R0_SILENT: 0.50,
    RiskTier.R1_NOTIFY: 0.60,
    RiskTier.R2_APPROVE: 0.75,
    RiskTier.R3_EXPLICIT_APPROVE: 0.88,
    RiskTier.R4_ESCALATE_ONLY: 0.92,
}

_TIER_STRICTNESS_ORDER: tuple[RiskTier, ...] = (
    RiskTier.R0_SILENT,
    RiskTier.R1_NOTIFY,
    RiskTier.R2_APPROVE,
    RiskTier.R3_EXPLICIT_APPROVE,
    RiskTier.R4_ESCALATE_ONLY,
)


class TestConfidenceFloor:
    @pytest.mark.parametrize(
        "tier,expected_floor",
        list(_EXPECTED_FLOORS.items()),
        ids=[tier.value for tier in _EXPECTED_FLOORS],
    )
    def test_floor_value(self, tier: RiskTier, expected_floor: float) -> None:
        assert confidence_floor(tier) == pytest.approx(expected_floor)

    def test_every_risk_tier_member_has_a_floor(self) -> None:
        """Tripwire against `contracts.actions.RiskTier` growing a new
        member (e.g. a future R5) with no corresponding floor decision
        made here — a `KeyError` on lookup is exactly the kind of silent
        gap spec §19.2 forbids for this module's own table."""
        for tier in RiskTier:
            assert confidence_floor(tier) is not None

    def test_floors_are_distinct_per_tier(self) -> None:
        floors = [confidence_floor(tier) for tier in RiskTier]
        assert len(floors) == len(set(floors)), "every RiskTier must have its own distinct floor"

    def test_floors_strictly_increase_with_strictness(self) -> None:
        """spec §19.2: 'safety-critical paths (hard constraints, payments,
        medical, voice) strictest.' R3 (payments) and R4 (medical among
        its examples) must be the two highest floors, and the full
        ordering must be monotonic — a stricter tier never has a laxer
        floor than a less-strict one."""
        floors_in_order = [confidence_floor(tier) for tier in _TIER_STRICTNESS_ORDER]
        assert floors_in_order == sorted(floors_in_order)
        assert len(set(floors_in_order)) == len(floors_in_order)

    def test_r3_and_r4_are_the_two_strictest_floors(self) -> None:
        r3_floor = confidence_floor(RiskTier.R3_EXPLICIT_APPROVE)
        r4_floor = confidence_floor(RiskTier.R4_ESCALATE_ONLY)
        other_floors = [
            confidence_floor(tier)
            for tier in RiskTier
            if tier not in (RiskTier.R3_EXPLICIT_APPROVE, RiskTier.R4_ESCALATE_ONLY)
        ]
        assert all(r3_floor > floor for floor in other_floors)
        assert all(r4_floor > floor for floor in other_floors)

    def test_all_floors_are_valid_probabilities(self) -> None:
        for tier in RiskTier:
            floor = confidence_floor(tier)
            assert 0.0 < floor <= 1.0


# ---------------------------------------------------------------------------
# apply_hard_constraint_floor — spec §18.2 rule 2.
# ---------------------------------------------------------------------------


class TestApplyHardConstraintFloor:
    @pytest.mark.parametrize("tier", [RiskTier.R0_SILENT, RiskTier.R1_NOTIFY])
    def test_below_r2_tiers_are_bumped_to_r2_when_hard_constraint_involved(self, tier: RiskTier) -> None:
        result = apply_hard_constraint_floor(tier, hard_constraint_involved=True)
        assert result is RiskTier.R2_APPROVE

    @pytest.mark.parametrize(
        "tier",
        [
            RiskTier.R2_APPROVE,
            RiskTier.R3_EXPLICIT_APPROVE,
            RiskTier.R4_ESCALATE_ONLY,
        ],
    )
    def test_r2_and_above_tiers_are_unaffected_when_hard_constraint_involved(self, tier: RiskTier) -> None:
        result = apply_hard_constraint_floor(tier, hard_constraint_involved=True)
        assert result is tier

    @pytest.mark.parametrize("tier", list(RiskTier))
    def test_no_hard_constraint_involvement_never_changes_the_tier(self, tier: RiskTier) -> None:
        result = apply_hard_constraint_floor(tier, hard_constraint_involved=False)
        assert result is tier

    def test_never_downgrades_strictness(self) -> None:
        """The rule is a floor, not a ceiling adjustment — an action
        already stricter than R2 must never come back *less* strict than
        it went in, regardless of hard-constraint involvement."""
        _TIER_ORDER = {tier: index for index, tier in enumerate(_TIER_STRICTNESS_ORDER)}
        for tier in RiskTier:
            for hard_constraint_involved in (True, False):
                result = apply_hard_constraint_floor(tier, hard_constraint_involved=hard_constraint_involved)
                assert _TIER_ORDER[result] >= _TIER_ORDER[tier]

    def test_r4_stays_r4_when_hard_constraint_involved(self) -> None:
        """Explicit worked example: an R4 action (e.g. a medical choice)
        that also involves a hard constraint stays at R4 — the ceiling —
        rather than being (nonsensically) treated as merely R2."""
        result = apply_hard_constraint_floor(RiskTier.R4_ESCALATE_ONLY, hard_constraint_involved=True)
        assert result is RiskTier.R4_ESCALATE_ONLY
