"""Tests for `app.reasoning.model_router` — Flash/Pro-tier routing and the
code-enforced Pro-tier allowlist.

PHASES.md Gate 2 checklist item: "Pro-tier allowlist enforced — a
non-allowlisted Pro call fails a test." This is that test.

`ModelRouter.route()` takes an injectable `client_factory` (DI, per
gharos-standards), so every test here substitutes a fake in place of the
real `google.genai.Client` constructor — these tests exercise routing and
allowlist logic only, never the real Vertex AI network call (that live
proof lives in `test_gemini_client.py`'s `live_gcp`-marked test and the
Phase 2 report).
"""

from __future__ import annotations

from typing import cast

import pytest
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google import genai

from app.reasoning.errors import InvalidRoutingTier, ProTierNotAllowlisted
from app.reasoning.model_router import PRO_TIER_ALLOWLIST, ModelRouter, RoutedModel

_PROJECT_ID = "gharos-test-project"
_LOCATION = "asia-south1"
_LOCATION_PRO = "global"
_MODEL_FLASH = "gemini-2.5-flash"
_MODEL_PRO = "gemini-2.5-pro"


class _FakeGenaiClient:
    """A minimal stand-in for `google.genai.Client` — records the
    construction args it was built with so a test can assert on them
    without ever touching the network or real ADC credentials."""

    def __init__(self, *, project_id: str, location: str) -> None:
        self.project_id = project_id
        self.location = location


def _fake_client_factory(project_id: str, location: str) -> genai.Client:
    """Injectable `ModelRouter.ClientFactory` returning a fake client.
    Cast to `genai.Client` for the type checker — `ModelRouter` only ever
    stores this on `RoutedModel.client` and never introspects its type,
    so a structurally-unrelated double is safe here (the same pattern
    `test_pubsub_receiver.py` uses for its injected `TokenVerifier`)."""
    return cast(genai.Client, _FakeGenaiClient(project_id=project_id, location=location))


def _router(*, location_pro: str | None = None) -> ModelRouter:
    return ModelRouter(
        project_id=_PROJECT_ID,
        location=_LOCATION,
        location_pro=location_pro,
        model_flash=_MODEL_FLASH,
        model_pro=_MODEL_PRO,
        client_factory=_fake_client_factory,
    )


class TestProTierAllowlistEnforcement:
    """The Gate 2 checklist item, proven directly."""

    def test_pro_tier_request_from_non_allowlisted_agent_raises(self) -> None:
        router = _router()
        non_allowlisted_agent_id = AgentId("A99")
        assert non_allowlisted_agent_id not in PRO_TIER_ALLOWLIST, (
            "test fixture assumption broken: A99 must not be a real allowlisted agent id"
        )

        with pytest.raises(ProTierNotAllowlisted) as exc_info:
            router.route(agent_id=non_allowlisted_agent_id, requested_tier=ModelTier.PRO)

        assert exc_info.value.agent_id == non_allowlisted_agent_id
        assert exc_info.value.requested_tier == ModelTier.PRO.value

    def test_pro_tier_request_from_allowlisted_agent_succeeds(self) -> None:
        router = _router()
        allowlisted_agent_id = AgentId("A12")
        assert allowlisted_agent_id in PRO_TIER_ALLOWLIST, (
            "test fixture assumption broken: A12 (Implication Agent) must be allowlisted"
        )

        routed = router.route(agent_id=allowlisted_agent_id, requested_tier=ModelTier.PRO)

        assert isinstance(routed, RoutedModel)
        assert routed.agent_id == allowlisted_agent_id
        assert routed.tier is ModelTier.PRO
        assert routed.model_name == _MODEL_PRO

    @pytest.mark.parametrize("agent_id", sorted(PRO_TIER_ALLOWLIST))
    def test_every_currently_allowlisted_agent_can_route_pro_tier(self, agent_id: AgentId) -> None:
        """Every id `PRO_TIER_ALLOWLIST` currently names actually routes
        successfully — a tripwire against an allowlist entry that looks
        right but is spelled wrong or otherwise dead.

        Parametrized directly off the live `PRO_TIER_ALLOWLIST` set, not a
        manually-copied literal list — a hand-maintained copy silently
        drifted out of sync with the real allowlist once already (Phase 3
        added A3/A3b/A3c/A12 to the allowlist without this test's list
        being updated to match, so it was quietly testing a strict subset
        while its own docstring claimed "every" — caught in the Phase 4
        gate review). Deriving the parametrization from the allowlist
        itself makes that drift structurally impossible to repeat."""
        router = _router()
        routed = router.route(agent_id=agent_id, requested_tier=ModelTier.PRO)
        assert routed.model_name == _MODEL_PRO


class TestFlashTierRouting:
    def test_flash_tier_request_needs_no_allowlist_membership(self) -> None:
        router = _router()
        non_allowlisted_agent_id = AgentId("A99")
        assert non_allowlisted_agent_id not in PRO_TIER_ALLOWLIST

        routed = router.route(agent_id=non_allowlisted_agent_id, requested_tier=ModelTier.FLASH)

        assert routed.tier is ModelTier.FLASH
        assert routed.model_name == _MODEL_FLASH


class TestPerTierLocationRouting:
    """DEBT-003 / ADR-010: Pro-tier and Flash-tier resolve through
    independently-configurable Vertex AI locations, since real Model
    Garden availability is genuinely asymmetric per model per region
    (`gemini-2.5-pro` 404s in `asia-south1` for this project, works via
    `"global"`) — the router must never silently use the same location
    for both tiers when a caller explicitly configured them differently."""

    def test_pro_tier_uses_the_configured_pro_location(self) -> None:
        router = _router(location_pro=_LOCATION_PRO)
        routed = router.route(agent_id=AgentId("A12"), requested_tier=ModelTier.PRO)
        client = cast(_FakeGenaiClient, routed.client)
        assert client.location == _LOCATION_PRO

    def test_flash_tier_uses_the_regional_location_even_when_pro_location_differs(self) -> None:
        router = _router(location_pro=_LOCATION_PRO)
        routed = router.route(agent_id=AgentId("A99"), requested_tier=ModelTier.FLASH)
        client = cast(_FakeGenaiClient, routed.client)
        assert client.location == _LOCATION

    def test_location_pro_defaults_to_the_regional_location_when_not_given(self) -> None:
        """Single-region routing remains the default for any caller that
        doesn't explicitly configure `location_pro` — this test would
        catch an accidental change to that default."""
        router = _router(location_pro=None)
        routed = router.route(agent_id=AgentId("A12"), requested_tier=ModelTier.PRO)
        client = cast(_FakeGenaiClient, routed.client)
        assert client.location == _LOCATION


class TestDeterministicTierRejected:
    def test_deterministic_tier_raises_invalid_routing_tier(self) -> None:
        router = _router()

        with pytest.raises(InvalidRoutingTier) as exc_info:
            router.route(agent_id=AgentId("A28"), requested_tier=ModelTier.DETERMINISTIC)

        assert exc_info.value.requested_tier == ModelTier.DETERMINISTIC.value
