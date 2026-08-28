"""A51 — Service Discovery (spec §13.2 Step 2, §15.10, PHASES.md Phase
10).

*Responsibility:* "Find candidate providers by relevant location and
service type." *Tools:* search, places (spec §15.10 A51) — concretely,
`app.tools.graph_read_tool.GraphReadTool` (T0, for real household
provider history) and `app.tools.provider_search_tool.ProviderSearchTool`
(T1, for fresh discovery — see that module's own docstring for the
honestly-scoped "no real Places API integrated this phase" statement).

## Model tier — a documented deviation from the roster's generic "Flash"

`.claude/skills/gharos-agent-roster/SKILL.md` lists A51 as Flash-tier.
This implementation makes **no live Gemini call at all** and reports
`ServiceDiscoveryResult.model_tier == "deterministic"` on every run — a
deliberate, checked judgment call, not an oversight (flagged explicitly
in this phase's own final report). Unlike A25's counterparty-availability
free text (genuinely ambiguous natural language needing interpretation)
or A28's fuzzy counterparty-string matching, every field this agent
produces — an existing `Provider` node's own structured fields, or
`ProviderSearchTool`'s already-structured synthetic listing — needs no
interpretation. Spec §21.1's own cost discipline ("Flash for high-volume
ingestion, normalization, routing... Pro-tier reserved for the hard
reasoning steps") gives no category this agent's actual work falls into;
a Flash call here would be decorative narration with nothing genuine to
narrate, exactly the case `app.agents.fair_allocator.load_monitor_agent`'s
own "nothing to narrate -> no call" precedent already establishes for a
different agent. `prompt_version` is therefore always `None` here (no
prompt was ever loaded).

*Forbidden:* implying a live external search happened — every synthetic
candidate's origin is named plainly on `ServiceDiscoveryResult.
discovery_source` (see that field's own docstring).
"""

from __future__ import annotations

import uuid

from contracts.errors import ToolFailure
from contracts.graph_types import AgentId, NodeId, Provider
from contracts.repositories import GraphReader
from contracts.tools import PermissionTier

from app.tools.graph_read_tool import GraphReadTool
from app.tools.provider_search_tool import ProviderSearchTool, SyntheticProviderListing
from app.tools.registry import ToolRegistry

from .types import ProviderCandidate, ServiceDiscoveryRequest, ServiceDiscoveryResult

AGENT_ID = AgentId("A51")


class ServiceDiscoveryAgent:
    """A51. Tool-registry-scoped to T0+T1 only — this class has no
    importable path to a write or gated capability, mirroring
    `app.agents.ledger.reconciliation_agent.ReconciliationAgent`'s
    "read-only by construction" discipline, generalised here to
    "read-and-search only by construction"."""

    def __init__(self, *, graph_reader: GraphReader) -> None:
        self._tool_registry = ToolRegistry(
            agent_id=AGENT_ID, allowed_tiers=frozenset({PermissionTier.T0_READ, PermissionTier.T1_SEARCH})
        )
        self._tool_registry.register(GraphReadTool(graph_reader=graph_reader))
        self._tool_registry.register(ProviderSearchTool())

    @property
    def tool_registry(self) -> ToolRegistry:
        """Exposed for the same reason `ReconciliationAgent.tool_registry`
        is: a Gate 10 CTO review or an adversarial test can inspect this
        agent's registered tools directly without running it."""
        return self._tool_registry

    def discover(self, request: ServiceDiscoveryRequest) -> ServiceDiscoveryResult:
        """Runs one discovery pass.

        Raises:
            contracts.errors.ToolFailure: the underlying `graph_reader` or
                `provider_search` tool call failed — never reinterpreted
                as "no candidates found" (safety invariant #7).
        """
        existing = self._resolve_existing(request.known_provider_ids, category=request.category)

        new_candidates: tuple[ProviderCandidate, ...] = ()
        if request.min_new_candidates > 0:
            listings = self._search_new(
                category=request.category,
                location_context=request.location_context,
                count=request.min_new_candidates,
            )
            new_candidates = tuple(self._to_candidate(listing) for listing in listings)

        return ServiceDiscoveryResult(
            candidates=existing + new_candidates,
            model_tier="deterministic",
            prompt_version=None,
            discovery_source="synthetic_directory",
            invocation_id=uuid.uuid4().hex,
        )

    def _resolve_existing(
        self, known_provider_ids: tuple[NodeId, ...], *, category: str
    ) -> tuple[ProviderCandidate, ...]:
        tool = self._tool_registry.get("graph_reader")
        assert isinstance(tool, GraphReadTool)  # registered by this class's own __init__, always present
        found: list[ProviderCandidate] = []
        for provider_id in known_provider_ids:
            result = tool.invoke(operation="get_node", node_id=str(provider_id))
            if not result.ok:
                raise ToolFailure(
                    tool_name="graph_reader", reason=result.error or "get_node failed", retryable=True
                )
            node = result.value
            if isinstance(node, Provider) and node.category == category:
                found.append(
                    ProviderCandidate(
                        provider_id=node.id,
                        name=node.name,
                        category=node.category,
                        rating=node.rating,
                        distance_km=node.distance_km,
                        availability_notes=node.availability_notes,
                        price_band=node.price_band,
                        specialisations=node.specialisations,
                        is_existing_household_provider=True,
                    )
                )
        return tuple(found)

    def _search_new(
        self, *, category: str, location_context: str, count: int
    ) -> tuple[SyntheticProviderListing, ...]:
        tool = self._tool_registry.get("provider_search")
        assert isinstance(tool, ProviderSearchTool)  # registered by this class's own __init__, always present
        result = tool.invoke(category=category, location_context=location_context, count=count)
        if not result.ok:
            raise ToolFailure(
                tool_name="provider_search", reason=result.error or "search failed", retryable=True
            )
        value = result.value
        assert isinstance(value, tuple)
        return tuple(item for item in value if isinstance(item, SyntheticProviderListing))

    def _to_candidate(self, listing: SyntheticProviderListing) -> ProviderCandidate:
        return ProviderCandidate(
            provider_id=NodeId(f"provider-candidate:{uuid.uuid4().hex}"),
            name=listing.name,
            category=listing.category,
            rating=listing.rating,
            distance_km=listing.distance_km,
            availability_notes=listing.availability_notes,
            price_band=listing.price_band,
            specialisations=listing.specialisations,
            is_existing_household_provider=False,
        )


__all__ = ["AGENT_ID", "ServiceDiscoveryAgent"]
