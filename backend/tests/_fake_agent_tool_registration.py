"""A mock agent-side call site — deliberately **not** under
`backend/app/arbitration/` — for `test_tool_registry.py`'s adversarial
proof that `ToolRegistry.register` rejects a T4/T5/T6 tool registration
attempted from anywhere outside the Approval Gate's own package.

Not a test module itself (no `test_*` name, never collected by pytest) —
mirrors `_gemini_fakes.py`'s established "shared non-test helper living in
`backend/tests/`" pattern.
"""

from __future__ import annotations

from contracts.tools import Registrable

from app.tools.registry import ToolRegistry


def attempt_gated_registration(registry: ToolRegistry, tool: Registrable) -> None:
    """Calls `registry.register(tool)` from *this* module — standing in
    for "some reasoning-agent module tries to register a gated tool onto
    its own registry." This module's `__name__`
    (`tests._fake_agent_tool_registration`) does not start with
    `app.arbitration`, so `ToolRegistry.register`'s caller-module check
    must reject this regardless of what `allowed_tiers` the registry was
    constructed with.
    """
    registry.register(tool)


__all__ = ["attempt_gated_registration"]
