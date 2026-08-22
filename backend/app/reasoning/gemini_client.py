"""A real, reusable Vertex AI Gemini call wrapper built on `model_router.py`.

PHASES.md Phase 2 work item ("a live Gemini 3.5+ call through Vertex AI")
and Gate 2 requirement 1 ("Gemini 3.5+ via Vertex AI responding..."). This
module is the single place a plain text-in/text-out Gemini call is made —
every caller (starting with `app.api.debug`'s `/debug/gemini-ping`, and
every one of the 69 roster agents from Phase 3 onward that needs a simple
generation call rather than the full ADK agent/tool loop) goes through
`GeminiClient.generate_text()` rather than touching `google.genai` or
`ModelRouter.route()` directly, so tier routing, the Pro-tier allowlist,
and failure handling are enforced in exactly one place.

Agents that need tool-calling, multi-turn state, or callbacks use the ADK
pattern in `backend/app/agents/base.py` instead (`gemini_model_for`,
consumed by `backend/app/agents/orchestration/stack_proof_agent.py`) — that
path also resolves its model through `ModelRouter.route()`, so both entry
points share the same allowlist enforcement.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from contracts.agents import ModelTier
from contracts.graph_types import AgentId
from google.genai import errors as genai_errors

from .errors import GeminiCallFailed
from .model_router import ModelRouter

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class GeminiCallResult:
    """A completed, successful Gemini call — never constructed for a
    failed or empty response (see `GeminiClient.generate_text`'s
    `Raises` section); a failed call always raises `GeminiCallFailed`
    instead (safety invariant #7 — no fabricated success)."""

    agent_id: AgentId
    tier: ModelTier
    model_name: str
    text: str
    produced_at: datetime


class GeminiClient:
    """Thin wrapper around a `ModelRouter`-resolved `google.genai.Client`
    for single-turn, text-in/text-out Gemini calls.

    Dependency-injected per gharos-standards: holds a `ModelRouter`
    instance, not a raw client — no module-level singleton, and every
    call re-resolves through the router so the allowlist is checked on
    every invocation, not just at construction time.
    """

    def __init__(self, *, router: ModelRouter) -> None:
        """Args:
        router: the `ModelRouter` this client resolves every call
            through. Owns the Pro-tier allowlist check and the model
            name resolution.
        """
        self._router = router

    def generate_text(self, *, agent_id: AgentId, tier: ModelTier, prompt: str) -> GeminiCallResult:
        """Makes one live text-generation call to Vertex AI Gemini.

        Args:
            agent_id: the calling agent's id — checked against
                `model_router.PRO_TIER_ALLOWLIST` when `tier` is
                `ModelTier.PRO`.
            tier: `ModelTier.FLASH` or `ModelTier.PRO`. `ModelTier.DETERMINISTIC`
                is rejected by `ModelRouter.route()` before any call is made.
            prompt: the raw text prompt to send.

        Returns:
            A `GeminiCallResult` carrying the response text and the
            resolved model name/tier actually used.

        Raises:
            ProTierNotAllowlisted: `tier` is `ModelTier.PRO` and
                `agent_id` is not on the allowlist (raised by
                `ModelRouter.route()`, propagates unchanged).
            InvalidRoutingTier: `tier` is `ModelTier.DETERMINISTIC`
                (raised by `ModelRouter.route()`, propagates unchanged).
            GeminiCallFailed: the underlying Vertex AI call raised, or
                returned a response with no text content — a failed or
                empty call is never reinterpreted as an empty success.
        """
        routed = self._router.route(agent_id=agent_id, requested_tier=tier)

        try:
            response = routed.client.models.generate_content(
                model=routed.model_name,
                contents=prompt,
            )
        except genai_errors.APIError as exc:
            logger.warning(
                "reasoning.gemini_client.call_failed",
                agent_id=agent_id,
                model_name=routed.model_name,
                tier=tier.value,
                reason=str(exc),
            )
            raise GeminiCallFailed(agent_id=agent_id, model_name=routed.model_name, reason=str(exc)) from exc

        text = response.text
        if not text:
            logger.warning(
                "reasoning.gemini_client.empty_response",
                agent_id=agent_id,
                model_name=routed.model_name,
                tier=tier.value,
            )
            raise GeminiCallFailed(
                agent_id=agent_id,
                model_name=routed.model_name,
                reason="Vertex AI returned no text content (empty or non-text response)",
            )

        logger.info(
            "reasoning.gemini_client.call_succeeded",
            agent_id=agent_id,
            model_name=routed.model_name,
            tier=tier.value,
        )
        return GeminiCallResult(
            agent_id=agent_id,
            tier=tier,
            model_name=routed.model_name,
            text=text,
            produced_at=datetime.now(UTC),
        )
