"""Structural proof that the Confidence Arbiter (and the Approval Gate it
hands off to) is the **only** path to action — spec §15.12, Phase 5 task
item 2: "Prove this structurally (no import path from
`backend/app/agents/consequence/` or similar reasoning packages to your
gated-tool/action-execution modules) with a test, not a comment."

Two independent static-analysis checks, both AST-based (not a substring
search — mirrors `tests/_ast_checks.py`'s established rationale for why
that matters: real code, not comments that merely discuss the rule):

1. **Import-graph check**: no `.py` file under `backend/app/agents/`
   contains an `import`/`from ... import` statement naming
   `app.arbitration` (or any submodule of it) or `contracts.tools`'s gated
   classes.
2. **Construction-site check**: no `GatedAction(`/`GraphWriteAction(`
   constructor call exists anywhere in `backend/app/` outside
   `backend/app/arbitration/` itself.

Together these are the literal "no import path... with a test, not a
comment" proof — not merely "no agent currently imports arbitration" (true
today) but "no agent even *could* construct an `Action` without first
importing this package, and nothing outside this package does."
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_APP_ROOT = _BACKEND_ROOT / "app"
_AGENTS_ROOT = _APP_ROOT / "agents"
_ARBITRATION_ROOT = _APP_ROOT / "arbitration"

_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "app.arbitration",
    "arbitration.actions",
    "arbitration.gated_tool",
    "arbitration.approval_gate",
)

_ACTION_CONSTRUCTOR_NAMES = frozenset({"GatedAction", "GraphWriteAction"})


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_module_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return names


def _call_function_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                names.append(func.id)
            elif isinstance(func, ast.Attribute):
                names.append(func.attr)
    return names


class TestNoAgentImportsArbitration:
    def test_agents_root_exists(self) -> None:
        # Sanity check the path resolution itself before asserting an
        # empty result is meaningful (an empty result over a *missing*
        # directory would prove nothing).
        assert _AGENTS_ROOT.is_dir(), f"expected {_AGENTS_ROOT} to exist"

    def test_no_module_under_backend_app_agents_imports_arbitration(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_AGENTS_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module_name in _imported_module_names(tree):
                if any(substring in module_name for substring in _FORBIDDEN_IMPORT_SUBSTRINGS):
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} imports {module_name!r}")
        assert violations == [], (
            "reasoning agents must have no import path to the arbitration/action-execution "
            "layer:\n" + "\n".join(violations)
        )

    def test_no_module_under_backend_app_agents_imports_approval_gated_tool(self) -> None:
        """Updated Phase 7 (superseding the original, stricter Phase 4-era
        version of this test, which banned agents from importing
        `contracts.tools` at all): Phase 5's `app.tools.registry.
        ToolRegistry` + `PermissionTier` mechanism is exactly how a
        reasoning agent is *supposed* to hold tier-scoped, adversarially-
        provable tool access now — A28 Reconciliation (T0-only) and A34
        Staff Payroll (T3-only, spec §15.7) both legitimately import
        `contracts.tools.PermissionTier` to construct their own registries
        (`backend/app/agents/ledger/`). Banning `contracts.tools` outright
        would make that pattern impossible and contradicts Gate 7's own
        design.

        The real, still-load-bearing invariant (e2.md: "a reasoning agent
        must have no import path to `contracts.tools.ApprovalGatedTool` or
        its subclasses") is narrower and is what this test now checks
        directly: no agent module ever imports the name
        `ApprovalGatedTool` from `contracts.tools` — the T4/T5/T6 gated-
        tool base class only `backend/app/arbitration/` may construct
        (spec §16.3; `contracts.tools.ApprovalGatedTool`'s own docstring).
        `GATED_TIERS` is checked alongside it for the same reason — an
        agent has no legitimate use for the gated-tier set at all, since
        `ToolRegistry.register` already refuses a GATED_TIERS tool from
        any non-`app.arbitration` caller regardless."""
        forbidden_names = {"ApprovalGatedTool", "GATED_TIERS"}
        violations: list[str] = []
        for path in _iter_python_files(_AGENTS_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.ImportFrom)
                    and node.module == "contracts.tools"
                    and any(alias.name in forbidden_names for alias in node.names)
                ):
                    violations.append(
                        f"{path.relative_to(_BACKEND_ROOT)} imports a gated-tool name from contracts.tools"
                    )
        assert violations == [], (
            "no reasoning agent should import ApprovalGatedTool/GATED_TIERS from contracts.tools:\n"
            + "\n".join(violations)
        )


class TestOnlyArbitrationConstructsActions:
    def test_arbitration_root_exists(self) -> None:
        assert _ARBITRATION_ROOT.is_dir(), f"expected {_ARBITRATION_ROOT} to exist"

    def test_no_action_constructor_call_outside_arbitration_package(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_APP_ROOT):
            if _ARBITRATION_ROOT in path.parents or path.parent == _ARBITRATION_ROOT:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _call_function_names(tree):
                if name in _ACTION_CONSTRUCTOR_NAMES:
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} calls {name}(...)")
        assert violations == [], (
            "only backend/app/arbitration/ may construct a contracts.actions.Action "
            "instance:\n" + "\n".join(violations)
        )

    def test_action_constructors_are_actually_used_within_arbitration(self) -> None:
        """Tripwire against the previous test passing vacuously (e.g. if
        `actions.py` were ever deleted) — the constructors must be called
        *somewhere* real within the sanctioned package."""
        found: set[str] = set()
        for path in _iter_python_files(_ARBITRATION_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            found.update(name for name in _call_function_names(tree) if name in _ACTION_CONSTRUCTOR_NAMES)
        assert found == _ACTION_CONSTRUCTOR_NAMES, (
            f"expected both action constructors used within app.arbitration, found: {found}"
        )
