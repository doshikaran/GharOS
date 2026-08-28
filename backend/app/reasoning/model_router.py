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
        # spec §21.1 "Multimodal ingestion... Flash / Pro-tier for
        # degraded" — Document Extraction Agent (Phase 3): Flash for
        # clean documents, Pro-tier only for degraded scans/handwriting
        # (spec §15.2 A3).
        "A3",
        # spec §21.1 "Multimodal ingestion... Flash / Pro-tier for
        # degraded" — Line-Item Extraction Agent (Phase 3): Pro-tier
        # multimodal specifically for degraded thermal receipts (spec
        # §15.2 A3b).
        "A3b",
        # spec §15.2 A3c Verification Agent (Phase 3) — Pro-tier per the
        # roster: interpreting whether a purchased item verifies or
        # contradicts a household constraint is judgment, not extraction.
        "A3c",
        # spec §21.1 "Cross-script entity resolution" — Entity Resolution
        # Agent (Phase 3), Flash by default, escalates to Pro-tier only on
        # ambiguity (spec §15.2 A5: never guess on hard-constraint-bearing
        # entities).
        "A5",
        # spec §21.1 "Implication reasoning" — the flagship Consequence
        # Engine agent (Phase 4). Deriving unstated obligations is
        # reasoning, not extraction.
        "A12",
        # spec §15.4 A13: "Flash for lookup, Pro-tier for interpretation
        # ('does may contain traces violate a nut allergy?' — yes, but
        # that's judgment)" — Constraint Checker (Phase 4). Escalates from
        # Flash the same way A5/A3 already do: on an ambiguous verdict, or
        # (since a HARD constraint's ambiguity must always escalate to a
        # human, never be guessed) whenever Flash's own confidence on a
        # HARD constraint doesn't clear its confidence floor.
        "A13",
        # spec §7.3 Stage 3 DECONFLICT / spec §15.4 A14: Conflict Radar
        # (Phase 4) reasons at Pro-tier over whatever E1's deterministic
        # pre-pass (`app.solvers.conflict_prepass`) could not resolve on
        # its own — newly implied candidates with no graph-resident
        # OWNED_BY edge yet to run the deterministic arithmetic against.
        "A14",
        # spec §15.4 A16: Constraint Learner (Phase 4) — judging whether a
        # repeated signal across multiple SOURCE_DOCUMENTs is genuinely a
        # new implicit household constraint is interpretation, not lookup.
        # Never writes anything itself (no `GraphWriter` import at all) —
        # `CandidateConstraint.status` is structurally pinned to
        # `"pending_confirmation"`, so this Pro-tier call can only ever
        # produce a human-confirmation candidate, never a written
        # constraint (spec §15.4 A16 forbidden list).
        "A16",
        # spec §15.8 A17: Interviewer (Phase 8) — "Flash for flow, Pro-tier
        # for question selection." Choosing which comparison to ask next
        # (avoiding a pair already implied by transitivity, prioritising
        # tasks nobody has an opinion on yet) is the real judgment call;
        # conducting the turn itself (parsing a free-text answer) stays
        # Flash — see `app.agents.fair_allocator.interviewer_agent`.
        "A17",
        # spec §21.1 "Valuation extraction" — Fair Allocator (Phase 8).
        # Mutating complaint streams into a cardinal cost matrix.
        "A18",
        # spec §15.8 A19: Fairness Verifier / Explainer (Phase 8) —
        # "verification deterministic... Pro-tier for explanation."
        # Verification itself never calls a model at all (`app.solvers.
        # fair_allocation.verify_ef1`, a real external checkable signal,
        # deliberately avoiding LLM self-critique); only explaining each
        # person's own share in their own valuations is a genuine Pro-tier
        # reasoning step.
        "A19",
        # spec §15.7 A28: Reconciliation Agent (Phase 7) — "Pro-tier for
        # matching; arithmetic delegated to a calculation tool." Matching a
        # messy raw counterparty string ("SUNRISE SOCIETY MAINT") to a
        # known RECURRING_COMMITMENT ("Sunrise Society maintenance") is
        # real fuzzy-matching judgment; duplicate/price-change/mismatch
        # detection stays plain deterministic code in
        # `app.agents.ledger.reconciliation_agent`, never a model call.
        "A28",
        # spec §15.7 A29: Leakage Detection (Phase 7) — the "worth
        # reasoning" step. Per-item judgment against real usage signal and
        # household priorities, deliberately never a rule-based cutoff.
        "A29",
        # spec §15.7 A30: Recovery Drafting (Phase 7) — drafting a real,
        # ready-to-review cancellation/dispute/claim message using a
        # learned per-merchant playbook is genuine drafting work, not a
        # template fill.
        "A30",
        # spec §15.7 A32: Dispute Branch (Phase 7) — writing a genuinely
        # neutral summary of two disagreeing figures without the wording
        # itself favouring either side is real judgment; the two figures
        # and the discrepancy amount themselves are always computed
        # deterministically, never by the model.
        "A32",
        # spec §15.7 A34: Staff Payroll (Phase 7) — "Pro-tier for
        # attendance interpretation; arithmetic deterministic." Only
        # called when a real ambiguous ("unknown") mark exists in a
        # staff member's `AttendanceRecord.daily_marks`; a clean register
        # makes no Gemini call at all
        # (`app.agents.ledger.staff_payroll_agent`).
        "A34",
        # spec §21.1 "Blocker diagnosis" — Intention->Action (Phase 9).
        # Judgment about why *this* person stalls on *this* task.
        "A23",
        # spec §15.9 A24: Unblocker / Preparation (Phase 9) — "Flash for
        # retrieval, Pro-tier for narrowing/drafting." Only
        # `narrow_decision`/`switch_modality`/`decompose_first_step` call
        # Pro-tier; `fetch_information` stays Flash
        # (`app.agents.intention_action.unblocker_agent`).
        "A24",
        # spec §15.9 A25: Window Scheduling (Phase 9) — "Flash with
        # Pro-tier fallback." Person-availability and historical-
        # likelihood are deterministic (no model call at all); only the
        # counterparty free-text interpretation escalates to Pro-tier on
        # ambiguity/low confidence
        # (`app.agents.intention_action.window_scheduling_agent`).
        "A25",
        # spec §15.9 A26: Slippage Analyst (Phase 9) — re-diagnosing
        # against a real attempt history and producing three real,
        # concrete escalation options grounded in real household data is
        # judgment, not lookup.
        "A26",
        # spec §21.1 "Branch simulation & critique" — Household Simulator
        # (Phase 11): A37 Path Simulator projects one branch.
        "A37",
        # spec §21.1 "Branch simulation & critique" — Household Simulator
        # (Phase 11): A38 Consistency Critic red-teams a branch.
        "A38",
        # spec §21.1 "Council specialist reasoning" — Household Council
        # (Phase 12) domain specialists, each reasoning over a distinct
        # subgraph (Finance/Care/Education/Logistics/Legal: A42/A43/A44/
        # A45/A46). A41 Convener, A47 Member Delegate and A48 Adversary
        # are also Pro-tier per the roster but are added when Phase 12
        # actually builds them, per gharos-agent-roster's per-agent tier
        # table — this allowlist is extended by whichever phase builds the
        # agent, not pre-populated ahead of the code that will use it.
        "A42",
        "A43",
        "A44",
        "A45",
        "A46",
        # spec §21.1 "Voice interaction (outbound)" — Outbound Concierge /
        # Voice interface (Phase 10/13): A54 conducts the call, Pro-tier
        # realtime.
        "A54",
        # spec §15.12 A57 Confidence Arbiter (Phase 5): "Deterministic
        # policy + Pro-tier for borderline." Every clear-cut decision is
        # plain code (`app.reasoning.risk_policy` + `contracts.actions`);
        # only a confidence score sitting within `ConfidenceArbiter`'s
        # narrow borderline band of its tier's floor escalates to a real
        # Pro-tier adjudication call — see `app.arbitration.
        # confidence_arbiter._BORDERLINE_BAND`.
        "A57",
        # spec §15.10 A50: Requirement Clarifier (Phase 10) — deciding
        # which genuinely-unknown facts are decision-relevant enough to
        # ask about (never more than the enforced two-question ceiling)
        # and detecting pain/urgency signals is real judgment over the
        # household's own request text, not lookup.
        "A50",
        # spec §15.10 A52: Provider Ranking (Phase 10) — the rank order
        # itself is deterministic (`app.agents.concierge.ranking`); this
        # agent's own Pro-tier call only narrates the already-final order
        # in natural language, but that narration is still a genuine
        # Pro-tier reasoning step over real, per-provider evidence.
        "A52",
        # spec §15.10 A53: Call Planner (Phase 10) — phrasing a complete,
        # natural call objective from a plain intent, a selected
        # provider, and authorised slots is real judgment; every bound
        # field on the `CallBrief` it produces is copied verbatim from
        # the household's own authorised bounds, never generated by this
        # call.
        "A53",
        # spec §15.10 A55: Confirmation Verifier (Phase 10) — the
        # verified/not-verified verdict itself is deterministic
        # (`app.agents.concierge.verification`, no model call at all);
        # this agent's Pro-tier call runs only when that structural check
        # already passed, to catch a genuine "wrong service" semantic
        # mismatch a structured bounds comparison cannot detect on its
        # own — and can only narrow an already-passing verdict, never
        # widen a failing one.
        "A55",
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
        location_pro: str | None = None,
        client_factory: ClientFactory = _default_client_factory,
    ) -> None:
        """Construct a router bound to one GCP project/model set, with an
        independently-configurable location per tier.

        Args:
            project_id: GCP project id Gemini calls are billed/scoped to
                (`app.settings.Settings.gcp_project_id`).
            location: Vertex AI location for Flash-tier calls
                (`app.settings.Settings.vertex_ai_location`) — regional,
                for latency.
            model_flash: Flash-tier model name
                (`app.settings.Settings.gemini_model_flash`).
            model_pro: Pro-tier model name
                (`app.settings.Settings.gemini_model_pro`).
            location_pro: Vertex AI location for Pro-tier calls
                (`app.settings.Settings.vertex_ai_location_pro`). Defaults
                to `location` (single-region routing) when not given —
                but real-world Model Garden availability is genuinely
                asymmetric per model per region (DEBT-003, resolved by
                ADR-010: `gemini-2.5-pro` 404s in `asia-south1` for this
                project, works via `"global"`), so Pro-tier routinely needs
                a different location than Flash. Two separate `genai.Client`
                instances get built (one per tier actually used in a given
                `route()` call), never a single client whose location is
                mutated between calls.
            client_factory: builds the underlying `genai.Client`; defaults
                to the real Vertex AI constructor. Tests inject a fake.
        """
        self._project_id = project_id
        self._location = location
        self._location_pro = location_pro if location_pro is not None else location
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

        is_pro = requested_tier is ModelTier.PRO
        model_name = self._model_pro if is_pro else self._model_flash
        location = self._location_pro if is_pro else self._location
        client = self._client_factory(self._project_id, location)

        logger.info(
            "reasoning.model_router.routed",
            agent_id=agent_id,
            tier=requested_tier.value,
            model_name=model_name,
            location=location,
        )
        return RoutedModel(agent_id=agent_id, tier=requested_tier, model_name=model_name, client=client)
