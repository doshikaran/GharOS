"""Tests for A51 Service Discovery
(`app.agents.concierge.service_discovery_agent`).

Gate 10's own acceptance list this file's share of: existing household
Provider history is surfaced with `is_existing_household_provider=True`;
a category with no real household history still produces plausible new
candidates via the honestly-labeled synthetic source; A51 holds no write
or gated capability (T0+T1 only, proven by test, not review comment).
"""

from __future__ import annotations

import pytest
from contracts.graph_types import NodeId, Provider
from contracts.tools import PermissionTier

from app.agents.concierge.service_discovery_agent import AGENT_ID, ServiceDiscoveryAgent
from app.agents.concierge.types import ServiceDiscoveryRequest
from app.tools.errors import GatedToolRegistrationDenied, ToolTierNotPermitted
from tests._fake_agent_tool_registration import attempt_gated_registration
from tests._fake_graph_reader import FakeGraphReader
from tests.conftest import make_provenance


class _DummyT3Tool:
    """Mirrors `test_reconciliation_agent.py`'s own `_DummyT3Tool` — a
    minimal `Registrable` test double at T3, used to prove A51's registry
    rejects a write tool even though T3 is not itself in `GATED_TIERS`."""

    def __init__(self) -> None:
        self.name = "graph_writer"
        self.tier = PermissionTier.T3_INTERNAL_WRITE


def _provider(node_id: str, *, category: str = "dentist", name: str = "Sunrise Dental") -> Provider:
    return Provider(
        id=NodeId(node_id),
        provenance=make_provenance(),
        name=name,
        category=category,
        rating=4.6,
        distance_km=1.2,
        availability_notes="Mon-Fri 9-6",
        price_band="$$",
        specialisations=("routine care",),
    )


class TestAgentIdentity:
    def test_agent_id_is_a51(self) -> None:
        assert str(AGENT_ID) == "A51"


class TestExistingProviderResolution:
    def test_existing_provider_in_category_is_surfaced_as_existing(self) -> None:
        provider = _provider("provider-1")
        reader = FakeGraphReader(nodes_by_id={"provider-1": provider})
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist",
                location_context="home",
                known_provider_ids=(NodeId("provider-1"),),
                min_new_candidates=0,
            )
        )
        assert len(result.candidates) == 1
        assert result.candidates[0].is_existing_household_provider is True
        assert result.candidates[0].provider_id == NodeId("provider-1")
        assert result.model_tier == "deterministic"
        assert result.prompt_version is None

    def test_known_provider_in_a_different_category_is_excluded(self) -> None:
        provider = _provider("provider-1", category="plumber")
        reader = FakeGraphReader(nodes_by_id={"provider-1": provider})
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist",
                location_context="home",
                known_provider_ids=(NodeId("provider-1"),),
                min_new_candidates=0,
            )
        )
        assert result.candidates == ()

    def test_unresolvable_known_id_is_silently_skipped_not_fabricated(self) -> None:
        reader = FakeGraphReader(nodes_by_id={})
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist",
                location_context="home",
                known_provider_ids=(NodeId("does-not-exist"),),
                min_new_candidates=0,
            )
        )
        assert result.candidates == ()


class TestFreshDiscovery:
    def test_min_new_candidates_produces_that_many_synthetic_candidates(self) -> None:
        reader = FakeGraphReader()
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist", location_context="home", known_provider_ids=(), min_new_candidates=2
            )
        )
        assert len(result.candidates) == 2
        assert all(candidate.is_existing_household_provider is False for candidate in result.candidates)
        assert result.discovery_source == "synthetic_directory"

    def test_new_candidate_ids_are_distinct_and_not_graph_ids(self) -> None:
        reader = FakeGraphReader()
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist", location_context="home", known_provider_ids=(), min_new_candidates=3
            )
        )
        ids = {candidate.provider_id for candidate in result.candidates}
        assert len(ids) == 3
        assert all(str(pid).startswith("provider-candidate:") for pid in ids)

    def test_existing_and_fresh_candidates_are_combined(self) -> None:
        provider = _provider("provider-1")
        reader = FakeGraphReader(nodes_by_id={"provider-1": provider})
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist",
                location_context="home",
                known_provider_ids=(NodeId("provider-1"),),
                min_new_candidates=2,
            )
        )
        assert len(result.candidates) == 3
        existing = [c for c in result.candidates if c.is_existing_household_provider]
        fresh = [c for c in result.candidates if not c.is_existing_household_provider]
        assert len(existing) == 1
        assert len(fresh) == 2

    def test_zero_min_new_candidates_makes_no_search_call(self) -> None:
        reader = FakeGraphReader()
        agent = ServiceDiscoveryAgent(graph_reader=reader)
        result = agent.discover(
            ServiceDiscoveryRequest(
                category="dentist", location_context="home", known_provider_ids=(), min_new_candidates=0
            )
        )
        assert result.candidates == ()


class TestReadAndSearchOnlyByConstruction:
    """Mirrors `test_reconciliation_agent.py`'s `TestReadOnlyByConstruction`
    — A51 is structurally incapable of writing or of holding a gated
    T4/T5/T6 tool, proven directly against its own `tool_registry`."""

    def test_tool_registry_holds_only_t0_and_t1(self) -> None:
        agent = ServiceDiscoveryAgent(graph_reader=FakeGraphReader())
        for tool in agent.tool_registry.tools():
            assert tool.tier in (PermissionTier.T0_READ, PermissionTier.T1_SEARCH)

    def test_registering_a_t3_tool_onto_a51s_registry_is_rejected(self) -> None:
        agent = ServiceDiscoveryAgent(graph_reader=FakeGraphReader())
        with pytest.raises(ToolTierNotPermitted):
            agent.tool_registry.register(_DummyT3Tool())

    def test_gated_tier_registration_from_agent_side_is_rejected(self) -> None:
        from app.arbitration.payment_tool import SandboxPaymentTool
        from tests._fake_idempotency_store import InMemoryIdempotencyStore

        agent = ServiceDiscoveryAgent(graph_reader=FakeGraphReader())
        tool = SandboxPaymentTool(
            graph_writer=None,  # type: ignore[arg-type]
            graph_reader=None,  # type: ignore[arg-type]
            idempotency_store=InMemoryIdempotencyStore(),
            bounds={},
        )
        with pytest.raises(GatedToolRegistrationDenied):
            attempt_gated_registration(agent.tool_registry, tool)
