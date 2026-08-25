"""`ToolRegistry` — the construction-time binding between one agent and the
tools it holds, permission-tier-checked (spec §16, PHASES.md Phase 5).

Two independent checks run on every `register()` call, in this order:

1. **Gated-tier origin check** (spec §16.3 invariant 2): a tool whose
   `tier` is in `contracts.tools.GATED_TIERS` (T4/T5/T6) may only be
   registered by code physically located under `backend/app/arbitration/`
   — checked via real call-stack introspection (`inspect.stack()`), not a
   flag a caller could set truthfully or falsely. This runs *before* the
   allowed-tiers check below and applies unconditionally, regardless of
   what tiers the registry claims to allow — a registry misconfigured to
   permit T6 is still refused a T6 tool if the caller isn't the Approval
   Gate's own code.
2. **Allowed-tiers check**: the tool's tier must be in the tiers this
   specific registry was constructed with. This is what makes "agent X
   cannot invoke T4/T5/T6" (or, for a Council specialist, "cannot read
   outside its own subgraph tier-equivalent") provable directly against a
   `ToolRegistry` instance built with that agent's real `allowed_tiers`,
   without needing to run the agent itself.

Both are proven adversarially in `backend/tests/test_tool_registry.py` —
see that file's docstring for the exact "mock agent-side location" test
Gate 5 asks for.
"""

from __future__ import annotations

import inspect

from contracts.graph_types import AgentId
from contracts.tools import GATED_TIERS, PermissionTier, Registrable

from .errors import GatedToolRegistrationDenied, ToolTierNotPermitted

_ARBITRATION_MODULE_PREFIX = "app.arbitration"
"""Every module permitted to register a GATED_TIERS tool must have a
`__name__` equal to this or starting with this + '.' — i.e. it must live
under `backend/app/arbitration/` (see that package's module docstring,
which mirrors `contracts.tools.ApprovalGatedTool`'s own docstring naming
this exact directory as the Approval Gate's home)."""


def _external_caller_module_name() -> str:
    """The `__name__` of whatever code called `ToolRegistry.register()` —
    two frames up from here (this helper's own frame, then `register`'s
    frame, then the real caller). Returns `""` if the stack is too shallow
    to resolve (defensive; never happens through a normal call, and an
    empty string never matches `_ARBITRATION_MODULE_PREFIX`, so it fails
    closed rather than open).
    """
    stack = inspect.stack()
    if len(stack) < 3:
        return ""
    return str(stack[2].frame.f_globals.get("__name__", ""))


def _is_arbitration_module(module_name: str) -> bool:
    return module_name == _ARBITRATION_MODULE_PREFIX or module_name.startswith(
        _ARBITRATION_MODULE_PREFIX + "."
    )


class ToolRegistry:
    """The set of tools one agent is wired against at construction time.

    Dependency-injected, per gharos-standards: holds no I/O itself, just
    the bookkeeping that makes "this agent's toolset never exceeds its
    permitted tiers" a checkable fact rather than a claim.
    """

    def __init__(self, *, agent_id: AgentId, allowed_tiers: frozenset[PermissionTier]) -> None:
        """Args:
        agent_id: the agent this registry is bound to — used only for
            error messages and test assertions, never for behaviour.
        allowed_tiers: the complete set of `PermissionTier`s this agent
            may hold tools for. Deliberately required (no default) —
            there is no sensible "allow everything" default for a system
            whose central claim is tier isolation.
        """
        self._agent_id = agent_id
        self._allowed_tiers = allowed_tiers
        self._tools: dict[str, Registrable] = {}

    @property
    def agent_id(self) -> AgentId:
        return self._agent_id

    @property
    def allowed_tiers(self) -> frozenset[PermissionTier]:
        return self._allowed_tiers

    def register(self, tool: Registrable) -> None:
        """Adds `tool` to this registry.

        Raises:
            GatedToolRegistrationDenied: `tool.tier` is in
                `contracts.tools.GATED_TIERS` and the immediate caller is
                not code under `backend/app/arbitration/`.
            ToolTierNotPermitted: `tool.tier` is not in this registry's
                `allowed_tiers`.
        """
        if tool.tier in GATED_TIERS:
            caller_module = _external_caller_module_name()
            if not _is_arbitration_module(caller_module):
                raise GatedToolRegistrationDenied(
                    tool_name=tool.name, tier=tool.tier.value, caller_module=caller_module
                )

        if tool.tier not in self._allowed_tiers:
            raise ToolTierNotPermitted(
                agent_id=str(self._agent_id),
                tool_name=tool.name,
                tier=tool.tier.value,
                allowed_tiers=tuple(sorted(t.value for t in self._allowed_tiers)),
            )

        self._tools[tool.name] = tool

    def tools(self) -> tuple[Registrable, ...]:
        return tuple(self._tools.values())

    def has_tier(self, tier: PermissionTier) -> bool:
        """True if this registry currently holds at least one tool at
        `tier` — the direct proof primitive for "agent X holds no T6
        tool"."""
        return any(tool.tier is tier for tool in self._tools.values())

    def get(self, name: str) -> Registrable | None:
        return self._tools.get(name)


__all__ = ["ToolRegistry"]
