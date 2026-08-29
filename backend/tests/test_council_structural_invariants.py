"""Gate 12's own structural checklist (PHASES.md Phase 12, spec §12.2),
proven as real, automated tests rather than manual review:

- **The word "debate" appears nowhere in code, comments, or prompts** —
  safety invariant 6 (spec §12.2: "Never describe the Council as agents
  debating to find the truth").
- **R4 never auto-resolves** — no module under `backend/app/agents/
  council/` imports `app.arbitration` or any gated (T4/T5/T6) tool
  machinery, and `contracts.graph_types.DecisionStatus.RESOLVED` is never
  referenced anywhere in this package (mirrors
  `test_action_construction_boundary.py`'s AST-based pattern — real code,
  not a comment that merely discusses the rule).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_COUNCIL_ROOT = _BACKEND_ROOT / "app" / "agents" / "council"
_PROMPTS_ROOT = _BACKEND_ROOT / "app" / "prompts"

_COUNCIL_PROMPT_DIRS = (
    "a41_council_convener",
    "a42_finance_specialist",
    "a43_care_specialist",
    "a44_education_specialist",
    "a45_logistics_specialist",
    "a46_legal_specialist",
    "a47_member_delegate",
    "a48_council_adversary",
)

_DEBATE_PATTERN = re.compile(r"debate", re.IGNORECASE)

_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "app.arbitration",
    "arbitration.actions",
    "arbitration.gated_tool",
    "arbitration.approval_gate",
)


def _iter_python_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _iter_prompt_files() -> list[Path]:
    files: list[Path] = []
    for dir_name in _COUNCIL_PROMPT_DIRS:
        prompt_dir = _PROMPTS_ROOT / dir_name
        if prompt_dir.is_dir():
            files.extend(sorted(prompt_dir.glob("*.md")))
    return files


def _imported_module_names(tree: ast.AST) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            names.append(node.module)
    return names


def _imported_names_from(tree: ast.AST, module: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.extend(alias.name for alias in node.names)
    return names


class TestCouncilRootExists:
    def test_council_root_exists(self) -> None:
        assert _COUNCIL_ROOT.is_dir(), f"expected {_COUNCIL_ROOT} to exist"


class TestNeverSaysDebate:
    """Safety invariant 6 (spec §12.2), Gate 12's own explicit checklist
    item: "The word 'debate' appears nowhere in code, comments, UI, or
    docs." Checked here for every `.py` file in this package and every
    `.md` prompt file A41-A48 load."""

    def test_no_python_file_in_council_package_contains_the_word_debate(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_COUNCIL_ROOT):
            text = path.read_text(encoding="utf-8")
            if _DEBATE_PATTERN.search(text):
                violations.append(str(path.relative_to(_BACKEND_ROOT)))
        assert violations == [], f"the word 'debate' must never appear in council code: {violations}"

    def test_no_council_prompt_file_contains_the_word_debate(self) -> None:
        prompt_files = _iter_prompt_files()
        assert prompt_files, "expected at least one A41-A48 prompt file to exist"
        violations: list[str] = []
        for path in prompt_files:
            text = path.read_text(encoding="utf-8")
            if _DEBATE_PATTERN.search(text):
                violations.append(str(path.relative_to(_BACKEND_ROOT)))
        assert violations == [], f"the word 'debate' must never appear in council prompts: {violations}"


class TestR4NeverAutoResolves:
    """No module under `backend/app/agents/council/` may import
    `app.arbitration` or any T4/T5/T6 gated-tool machinery, and
    `DecisionStatus.RESOLVED` is never referenced anywhere in this
    package — the Council produces a brief only (spec §12.2 design rule 5,
    Gate 12: "R4 never auto-resolves")."""

    def test_no_council_module_imports_arbitration(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_COUNCIL_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module_name in _imported_module_names(tree):
                if any(substring in module_name for substring in _FORBIDDEN_IMPORT_SUBSTRINGS):
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} imports {module_name!r}")
        assert violations == [], f"no Council module may import the arbitration layer: {violations}"

    def test_no_council_module_imports_gated_tool_names(self) -> None:
        forbidden_names = {"ApprovalGatedTool", "GATED_TIERS"}
        violations: list[str] = []
        for path in _iter_python_files(_COUNCIL_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = set(_imported_names_from(tree, "contracts.tools"))
            hit = imported & forbidden_names
            if hit:
                violations.append(f"{path.relative_to(_BACKEND_ROOT)} imports {sorted(hit)}")
        assert violations == [], f"no Council module may import a gated-tool name: {violations}"

    def test_decisionstatus_resolved_is_never_referenced_in_council_package(self) -> None:
        violations: list[str] = []
        for path in _iter_python_files(_COUNCIL_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Attribute)
                    and node.attr == "RESOLVED"
                    and isinstance(node.value, ast.Name)
                    and node.value.id == "DecisionStatus"
                ):
                    violations.append(str(path.relative_to(_BACKEND_ROOT)))
        assert violations == [], f"DecisionStatus.RESOLVED must never be referenced here: {violations}"

    def test_decisionstatus_is_never_imported_in_council_package(self) -> None:
        """Stronger than the attribute-access check above: no module in
        this package needs `DecisionStatus` at all — A41's own convening
        write uses `DecisionStatus.OPEN` (imported there, the one
        legitimate case), so this asserts specifically that no module
        *other than* `convener_agent.py` imports it."""
        violations: list[str] = []
        for path in _iter_python_files(_COUNCIL_ROOT):
            if path.name == "convener_agent.py":
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if "DecisionStatus" in _imported_names_from(tree, "contracts.graph_types"):
                violations.append(str(path.relative_to(_BACKEND_ROOT)))
        assert violations == [], f"only convener_agent.py may import DecisionStatus: {violations}"
