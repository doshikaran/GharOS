"""Typed errors for `backend/app/tools/` — the permission-tier tool layer
(spec §16, PHASES.md Phase 5).

`contracts/errors.py` is frozen and CTO-owned; it defines the failure
taxonomy every tool's *effect* raises (`ToolFailure`, `ApprovalRequired`,
`OutOfBounds`, `IdempotencyConflict`). The errors below are local to this
package's own boundary concern — *registering* a tool against a
`ToolRegistry` — which the frozen contract deliberately leaves to E3 to
define (mirrors the precedent `app.audit.errors`, `app.persistence.errors`,
and `app.agents.consequence.errors` already set for their own packages).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations


class ToolRegistryError(Exception):
    """Base class for every typed error raised by `backend/app/tools/registry.py`.

    Mirrors the role `contracts.errors.GharOSError` plays for the graph and
    action layers, scoped to code E3 owns in this package.
    """


class GatedToolRegistrationDenied(ToolRegistryError):
    """Raised when code outside `backend/app/arbitration/` attempts to
    register a T4/T5/T6 tool (`contracts.tools.GATED_TIERS`) with a
    `ToolRegistry`.

    This is spec §16.3 isolation invariant 2 ("T4, T5 and T6 are reachable
    ONLY through the Approval Gate") made structural at the registry
    boundary, not just at the import-graph level: even a caller that
    somehow obtained a gated tool instance cannot make it *usable* by an
    agent's registry from outside the Approval Gate's own module. See
    `ToolRegistry.register`'s docstring for the exact caller-module check.
    """

    def __init__(self, *, tool_name: str, tier: str, caller_module: str) -> None:
        self.tool_name = tool_name
        self.tier = tier
        self.caller_module = caller_module
        super().__init__(
            f"tool '{tool_name}' (tier {tier}) may only be registered from "
            f"backend/app/arbitration/ — attempted from module {caller_module!r}"
        )


class ToolTierNotPermitted(ToolRegistryError):
    """Raised when a `ToolRegistry` bound to one agent's `allowed_tiers` is
    asked to register a tool whose `tier` is not in that set — the
    mechanism behind Gate 5's "a reasoning agent cannot invoke T4/T5/T6 —
    proven by test, not review": constructing a registry for a reasoning
    agent with `allowed_tiers` capped at T0-T3 and then attempting to
    register any higher-tier tool must fail exactly here.
    """

    def __init__(self, *, agent_id: str, tool_name: str, tier: str, allowed_tiers: tuple[str, ...]) -> None:
        self.agent_id = agent_id
        self.tool_name = tool_name
        self.tier = tier
        self.allowed_tiers = allowed_tiers
        super().__init__(
            f"agent '{agent_id}' is not permitted tier {tier} (tool '{tool_name}') — "
            f"its registry allows only {allowed_tiers}"
        )


__all__ = ["GatedToolRegistrationDenied", "ToolRegistryError", "ToolTierNotPermitted"]
