"""Flash/Pro-tier model routing with a code-enforced Pro-tier allowlist.

PHASES.md Phase 2 work item ("`reasoning/model_router.py` — Flash/Pro-tier
routing with an allowlist for Pro-tier callers") and spec §21.1's cost
discipline: "Flash for high-volume ingestion, normalization, routing, and
bulk consolidation; Pro-tier reserved for the hard reasoning steps." This
module is *the* code-level enforcement point — every one of the 69 agents
in spec §15 that ever needs a live Gemini call goes through
`ModelRouter.route()` rather than constructing a `google.genai.Client`
itself, so the allowlist cannot be bypassed by a call site that "forgets."

A Pro-tier request from an agent not in `PRO_TIER_ALLOWLIST` raises
`reasoning.errors.ProTierNotAllowlisted` — a test failure, not a warning
(PHASES.md Gate 2: "Pro-tier allowlist enforced — a non-allowlisted Pro
call fails a test").

**This is genuinely reusable infrastructure, not a Phase 2 demo stub.**
`GeminiClient` (`reasoning/gemini_client.py`) is built on top of it, and
every LLM-backed agent from Phase 3 onward is expected to obtain its model
client through a `ModelRouter`, never directly through `google.genai`.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google import genai

from .errors import InvalidRoutingTier, ProTierNotAllowlisted

logger = structlog.get_logger(__name__)

PRO_TIER_ALLOWLIST: frozenset[AgentId] = frozenset(
    AgentId(agent_id)
    for agent_id in (
        # spec §21.1 "Cross-script entity resolution" — Entity Resolution
        # Agent (Phase 3), Flash by default, escalates to Pro-tier only on
        # ambiguity (spec §15.2 A5: never guess on hard-constraint-bearing
        # entities).
        "A5",
        # spec §21.1 "Implication reasoning" — the flagship Consequence
        # Engine agent (Phase 4). Deriving unstated obligations is
        # reasoning, not extraction.
        "A12",
        # spec §21.1 "Implication reasoning" — the flagship Consequence
        # Engine agent (Phase 4). Deriving unstated obligations is
        # reasoning, not extraction.
        "A18",
        # spec §21.1 "Valuation extraction" — Fair Allocator (Phase 8).
        # Mutating complaint streams into a cardinal cost matrix.
        "A23",
        # spec §21.1 "Blocker diagnosis" — Intention->Action (Phase 9).
        # Judgment about why *this* person stalls on *this* task.
        "A37",
        # spec §21.1 "Branch simulation & critique" — Household Simulator
        # (Phase 11): A37 Path Simulator projects one branch.
        "A38",
        # spec §21.1 "Branch simulation & critique" — Household Simulator
        # (Phase 11): A38 Consistency Critic red-teams a branch.
        "A42",
        # spec §21.1 "Council specialist reasoning" — Household Council
        # (Phase 12) domain specialists, each reasoning over a distinct
        # subgraph (Finance/Care/Education/Logistics/Legal). A41 Convener,
        # A47 Member Delegate and A48 Adversary are also Pro-tier per the
        # roster but are added when Phase 12 actually builds them, per
        # gharos-agent-roster's per-agent tier table — this allowlist is
        # extended by whichever phase builds the agent, not pre-populated
        # ahead of the code that will use it.
        "A43",
        "A44",
        "A45",
        "A46",
        # spec §21.1 "Voice interaction (outbound)" — Outbound Concierge /
        # Voice interface (Phase 10/13): A54 conducts the call, Pro-tier
        # realtime.
        "A54",
    )
)
"""Agent ids permitted to request `ModelTier.PRO`.

Minimal, spec-traceable set for Phase 2 (PHASES.md Gate 2 requires the
*mechanism*, not an exhaustive pre-population of agents that do not exist
as code yet). Each entry is commented with the spec §21.1 category and the
phase that will actually build it. Later phases extend this frozenset as
they build the next Pro-tier agent named in spec §21.1 — they do not
invent new categories.
"""


ClientFactory = Callable[[str, str], genai.Client]
"""Builds a `google.genai.Client` given `(project_id, location)`. Injected
so tests can supply a fake without needing real GCP credentials, and so a
future caller could swap in a differently-configured client (e.g. a
sandbox project) without touching routing logic."""


def _default_client_factory(project_id: str, location: str) -> genai.Client:
    """Real `google.genai.Client` construction against Vertex AI.

    Construction itself makes no network call (confirmed against the
    installed SDK version) — the client is a thin configuration object;
    the network round trip happens on the first `generate_content` call.
    """
    return genai.Client(vertexai=True, project=project_id, location=location)


@dataclass(frozen=True, slots=True)
class RoutedModel:
    """A resolved, ready-to-call model binding for one agent invocation.

    Returned by `ModelRouter.route()` once the allowlist check has passed
    (or was not required, for `ModelTier.FLASH`). Carries the configured
    `google.genai.Client` plus enough context (`agent_id`, `tier`,
    `model_name`) for the caller to populate `contracts.agents.AgentOutput`
    correctly without re-deriving it.
    """

    agent_id: AgentId
    tier: ModelTier
    model_name: str
    client: genai.Client


class ModelRouter:
    """Resolves an `(AgentId, ModelTier)` pair to a configured Vertex AI
    Gemini client, enforcing the Pro-tier allowlist in code.

    Dependency-injected, per gharos-standards: no module-level singleton
    holds the `genai.Client`. `settings` and `client_factory` are both
    injectable so unit tests exercise the real routing/allowlist logic
    without needing real GCP credentials or making a network call.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str,
        model_flash: str,
        model_pro: str,
        client_factory: ClientFactory = _default_client_factory,
    ) -> None:
        """Construct a router bound to one GCP project/location/model set.

        Args:
            project_id: GCP project id Gemini calls are billed/scoped to
                (`app.settings.Settings.gcp_project_id`).
            location: Vertex AI location for the underlying client
                (`app.settings.Settings.vertex_ai_location`).
            model_flash: Flash-tier model name
                (`app.settings.Settings.gemini_model_flash`).
            model_pro: Pro-tier model name
                (`app.settings.Settings.gemini_model_pro`).
            client_factory: builds the underlying `genai.Client`; defaults
                to the real Vertex AI constructor. Tests inject a fake.
        """
        self._project_id = project_id
        self._location = location
        self._model_flash = model_flash
        self._model_pro = model_pro
        self._client_factory = client_factory

    def route(self, *, agent_id: AgentId, requested_tier: ModelTier) -> RoutedModel:
        """Resolve `agent_id`'s request for `requested_tier` to a callable
        model binding.

        Args:
            agent_id: the requesting agent's id (`contracts.graph_types.AgentId`,
                e.g. `AgentId("A12")`).
            requested_tier: the tier the agent wants to call at.

        Returns:
            A `RoutedModel` carrying a configured `genai.Client` and the
            resolved model name.

        Raises:
            ProTierNotAllowlisted: `requested_tier` is `ModelTier.PRO` and
                `agent_id` is not in `PRO_TIER_ALLOWLIST`.
            InvalidRoutingTier: `requested_tier` is `ModelTier.DETERMINISTIC`
                — deterministic agents make no LLM call and must not route
                through here.
        """
        if requested_tier is ModelTier.DETERMINISTIC:
            raise InvalidRoutingTier(requested_tier=requested_tier.value)

        if requested_tier is ModelTier.PRO and agent_id not in PRO_TIER_ALLOWLIST:
            logger.warning(
                "reasoning.model_router.pro_tier_denied",
                agent_id=agent_id,
                requested_tier=requested_tier.value,
            )
            raise ProTierNotAllowlisted(agent_id=agent_id, requested_tier=requested_tier.value)

        model_name = self._model_pro if requested_tier is ModelTier.PRO else self._model_flash
        client = self._client_factory(self._project_id, self._location)

        logger.info(
            "reasoning.model_router.routed",
            agent_id=agent_id,
            tier=requested_tier.value,
            model_name=model_name,
        )
        return RoutedModel(agent_id=agent_id, tier=requested_tier, model_name=model_name, client=client)
