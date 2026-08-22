"""Typed errors for the reasoning layer (`backend/app/reasoning/`).

`contracts/errors.py` is frozen and CTO-only — it defines the graph- and
action-layer error taxonomy that every subsystem shares. The reasoning
layer's own failure modes (an agent invoking a model tier it is not
allowlisted for, a live Gemini call failing) do not fit that taxonomy and
are not the CTO's to define, so they live here instead.

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions —
every expected reasoning-layer failure path raises one of these, never a
generic `Exception`, and a failed call is never reinterpreted as a
success (safety invariant #7).
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class ReasoningError(Exception):
    """Base class for every typed error raised by `backend/app/reasoning/`.

    Mirrors the role `contracts.errors.GharOSError` plays for the graph
    and action layers, scoped to code E2 owns.
    """


class ProTierNotAllowlisted(ReasoningError):
    """Raised when an agent not on `model_router.PRO_TIER_ALLOWLIST`
    requests `ModelTier.PRO`.

    This is the code-level enforcement of spec §21.1's cost-discipline
    rule ("Pro-tier reserved for the hard reasoning steps") and
    PHASES.md Gate 2's explicit checklist item: "Pro-tier allowlist
    enforced — a non-allowlisted Pro call fails a test." Raising this is
    the *only* way a disallowed Pro-tier call can be observed — it must
    never be silently downgraded to Flash or allowed through with a
    warning.
    """

    def __init__(self, *, agent_id: AgentId, requested_tier: str) -> None:
        self.agent_id = agent_id
        self.requested_tier = requested_tier
        super().__init__(
            f"agent '{agent_id}' is not on the Pro-tier allowlist (requested tier: {requested_tier})"
        )


class InvalidRoutingTier(ReasoningError):
    """Raised when `model_router.route()` is asked to resolve a live model
    client for a tier that has no corresponding Gemini model —
    `ModelTier.DETERMINISTIC` agents (the fairness solver, the mechanism
    arbiter, the salary calculator, ...) never call an LLM at all and
    must not go through this router."""

    def __init__(self, *, requested_tier: str) -> None:
        self.requested_tier = requested_tier
        super().__init__(
            f"model_router.route() cannot resolve a model client for tier "
            f"'{requested_tier}' — DETERMINISTIC agents make no LLM call"
        )


class GeminiCallFailed(ReasoningError):
    """Raised when a live call to Vertex AI Gemini fails.

    The only acceptable way `GeminiClient` reports a failed model call —
    a failed call is never reinterpreted as an empty or fabricated
    success (safety invariant #7). Wraps the underlying
    `google.genai.errors.APIError` (or any other unexpected exception
    from the SDK call) with the calling agent's context; the original
    exception is always chained via `raise ... from exc`.
    """

    def __init__(self, *, agent_id: AgentId, model_name: str, reason: str) -> None:
        self.agent_id = agent_id
        self.model_name = model_name
        self.reason = reason
        super().__init__(f"Gemini call failed for agent '{agent_id}' on model '{model_name}': {reason}")
