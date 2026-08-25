"""Tests for `app.tools.registry.ToolRegistry` — PHASES.md Gate 5: "A
reasoning agent cannot invoke T4/T5/T6 — proven by test, not review."

Two structural claims are proven here, adversarially:

1. A `ToolRegistry` bound to an agent's `allowed_tiers` rejects any tool
   whose tier is not in that set (`ToolTierNotPermitted`) — this is what
   makes "agent X's toolset never exceeds its permitted tiers" checkable
   directly against a registry instance built with that agent's real
   tiers, without running the agent.
2. A T4/T5/T6 (`contracts.tools.GATED_TIERS`) tool can only ever be
   registered by code physically under `backend/app/arbitration/` —
   `test_gated_tier_registration_rejected_from_mock_agent_side_location`
   is the literal "attempt exactly that registration from a mock
   agent-side location and assert it is rejected" proof the task asked
   for, using `_fake_agent_tool_registration.py` (a module deliberately
   outside `app.arbitration`) as the mock agent-side call site — and
   `test_gated_tier_registration_allowed_from_within_arbitration_module`
   is the matching positive-path proof, using the real
   `app.arbitration.gated_tool.register_gated_tool` call site.
"""

from __future__ import annotations

import pytest
from contracts.actions import ActionResult
from contracts.graph_types import AgentId
from contracts.tools import PermissionTier

from app.arbitration.gated_tool import ReferenceGatedTool, register_gated_tool
from app.tools.errors import GatedToolRegistrationDenied, ToolTierNotPermitted
from app.tools.registry import ToolRegistry

from ._fake_agent_tool_registration import attempt_gated_registration
from ._fake_idempotency_store import InMemoryIdempotencyStore


class _DummyTool:
    """A minimal, non-gated `contracts.tools.Tool` test double."""

    def __init__(self, *, name: str, tier: PermissionTier) -> None:
        self.name = name
        self.tier = tier

    def invoke(self, **kwargs: object) -> ActionResult[object]:
        return ActionResult.success(None)


def _reference_gated_tool(tier: PermissionTier = PermissionTier.T6_FINANCIAL) -> ReferenceGatedTool:
    return ReferenceGatedTool(
        name="reference_gated_tool",
        tier=tier,
        bounds={},
        effect=lambda **kwargs: "ok",
        idempotency_store=InMemoryIdempotencyStore(),
    )


class TestAllowedTiersEnforcement:
    def test_register_allows_a_tool_within_allowed_tiers(self) -> None:
        registry = ToolRegistry(agent_id=AgentId("A12"), allowed_tiers=frozenset({PermissionTier.T0_READ}))
        registry.register(_DummyTool(name="reader", tier=PermissionTier.T0_READ))
        assert registry.has_tier(PermissionTier.T0_READ)
        assert len(registry.tools()) == 1

    def test_register_rejects_a_tool_outside_allowed_tiers(self) -> None:
        """A12 (Implication Agent) is T0-only per the roster — attempting to
        hand it a T2 draft tool must be refused."""
        registry = ToolRegistry(agent_id=AgentId("A12"), allowed_tiers=frozenset({PermissionTier.T0_READ}))
        with pytest.raises(ToolTierNotPermitted) as exc_info:
            registry.register(_DummyTool(name="drafter", tier=PermissionTier.T2_DRAFT))
        assert exc_info.value.agent_id == "A12"
        assert not registry.has_tier(PermissionTier.T2_DRAFT)

    def test_reasoning_agent_registry_capped_below_t4_rejects_t4(self) -> None:
        """The literal Gate 5 claim: a reasoning agent's registry, built
        with its real (T0-T3) allowed tiers, cannot come to hold a T4 tool
        — proven directly against the registry, no agent execution
        needed."""
        registry = ToolRegistry(
            agent_id=AgentId("A15"),
            allowed_tiers=frozenset({PermissionTier.T0_READ, PermissionTier.T3_INTERNAL_WRITE}),
        )
        with pytest.raises((ToolTierNotPermitted, GatedToolRegistrationDenied)):
            registry.register(
                _DummyTool(name="message_sender", tier=PermissionTier.T4_EXTERNAL_COMMUNICATION)
            )
        assert not registry.has_tier(PermissionTier.T4_EXTERNAL_COMMUNICATION)


class TestGatedTierOriginEnforcement:
    def test_gated_tier_registration_rejected_from_mock_agent_side_location(self) -> None:
        """The adversarial proof: even a registry whose `allowed_tiers`
        *does* include T6 refuses a T6 tool when the call site is not
        `app.arbitration` — the origin check is unconditional, not merely
        an allowed-tiers convenience."""
        registry = ToolRegistry(
            agent_id=AgentId("fake-agent"),
            allowed_tiers=frozenset({PermissionTier.T6_FINANCIAL}),
        )
        tool = _reference_gated_tool(PermissionTier.T6_FINANCIAL)

        with pytest.raises(GatedToolRegistrationDenied) as exc_info:
            attempt_gated_registration(registry, tool)

        assert exc_info.value.tool_name == "reference_gated_tool"
        assert exc_info.value.tier == "T6"
        assert "app.arbitration" not in exc_info.value.caller_module
        assert not registry.has_tier(PermissionTier.T6_FINANCIAL)

    @pytest.mark.parametrize(
        "tier",
        [
            PermissionTier.T4_EXTERNAL_COMMUNICATION,
            PermissionTier.T5_VOICE_OUTBOUND,
            PermissionTier.T6_FINANCIAL,
        ],
    )
    def test_every_gated_tier_rejected_from_agent_side_location(self, tier: PermissionTier) -> None:
        registry = ToolRegistry(agent_id=AgentId("fake-agent"), allowed_tiers=frozenset({tier}))
        tool = _reference_gated_tool(tier)
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(registry, tool)

    def test_gated_tier_registration_allowed_from_within_arbitration_module(self) -> None:
        """The matching positive-path proof: the exact same tool, the exact
        same registry shape, registered via the real
        `app.arbitration.gated_tool.register_gated_tool` call site,
        succeeds."""
        registry = ToolRegistry(
            agent_id=AgentId("approval-gate"), allowed_tiers=frozenset({PermissionTier.T6_FINANCIAL})
        )
        tool = _reference_gated_tool(PermissionTier.T6_FINANCIAL)

        register_gated_tool(registry, tool)

        assert registry.has_tier(PermissionTier.T6_FINANCIAL)
        assert registry.get("reference_gated_tool") is tool

    def test_non_gated_tiers_are_unaffected_by_the_origin_check(self) -> None:
        """T0-T3 tools have no origin restriction at all — the gated-tier
        check must not fire for them regardless of call site."""
        registry = ToolRegistry(
            agent_id=AgentId("fake-agent"), allowed_tiers=frozenset({PermissionTier.T0_READ})
        )
        attempt_gated_registration(registry, _DummyTool(name="reader", tier=PermissionTier.T0_READ))
        assert registry.has_tier(PermissionTier.T0_READ)
