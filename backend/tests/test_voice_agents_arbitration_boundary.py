"""Structural proof that E2's inbound-voice reasoning agents (A64, A65,
A67, A68 — `backend/app/agents/voice/`) hold no import path to the
arbitration/action-execution layer and no tool above T0/T2 — E2's own,
independently-true half of safety invariant 8 (PHASES.md Phase 13,
ADR-020 Decision 5: "each of the four modules... independently,
unconditionally true").

Mirrors `test_action_construction_boundary.py`'s established AST-based
technique exactly (real code, not comments that merely discuss the rule)
and `test_council_structural_invariants.py`/`test_confirmation_verifier_
agent.py`'s per-package narrower scoping of the same check.

Two independent static-analysis checks:

1. **Import-graph check**: no `.py` file under `backend/app/agents/voice/`
   imports `app.arbitration` (or any submodule) or a gated-tool name from
   `contracts.tools`.
2. **No gated/T3+ tool construction**: no module under
   `backend/app/agents/voice/` constructs a `ToolRegistry` at all — these
   four agents hold no tool of any kind (they classify, tag, and judge;
   nothing here executes), which is a stronger, simpler guarantee than
   "only T0/T2" and is proven directly by the absence of any tool
   registry construction in the package.
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_VOICE_AGENTS_ROOT = _BACKEND_ROOT / "app" / "agents" / "voice"

_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "app.arbitration",
    "arbitration.actions",
    "arbitration.gated_tool",
    "arbitration.approval_gate",
)


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


class TestVoiceAgentsRootExists:
    def test_voice_agents_root_exists(self) -> None:
        assert _VOICE_AGENTS_ROOT.is_dir(), f"expected {_VOICE_AGENTS_ROOT} to exist"


class TestNoVoiceAgentImportsArbitration:
    def test_no_module_under_voice_package_imports_arbitration(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_VOICE_AGENTS_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module_name in _imported_module_names(tree):
                if any(substring in module_name for substring in _FORBIDDEN_IMPORT_SUBSTRINGS):
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} imports {module_name!r}")
        assert violations == [], (
            "inbound-voice reasoning agents must have no import path to the arbitration/"
            "action-execution layer:\n" + "\n".join(violations)
        )

    def test_no_module_under_voice_package_imports_a_gated_tool_name(self) -> None:
        forbidden_names = {"ApprovalGatedTool", "GATED_TIERS"}
        violations: list[str] = []
        for path in _iter_python_files(_VOICE_AGENTS_ROOT):
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
            "no inbound-voice reasoning agent should import ApprovalGatedTool/GATED_TIERS "
            "from contracts.tools:\n" + "\n".join(violations)
        )


class TestNoVoiceAgentHoldsAnyToolAtAll:
    """A64/A65/A67/A68 classify, tag, and judge — none of them acts, and
    none of them needs a tool of any kind. Proven directly: no module in
    this package ever constructs a `ToolRegistry`, which is a strictly
    stronger guarantee than "only T0/T2 tools"."""

    def test_no_module_under_voice_package_constructs_a_tool_registry(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_VOICE_AGENTS_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _call_function_names(tree):
                if name == "ToolRegistry":
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} constructs a ToolRegistry")
        assert violations == [], (
            "no inbound-voice reasoning agent should hold any tool at all:\n" + "\n".join(violations)
        )
