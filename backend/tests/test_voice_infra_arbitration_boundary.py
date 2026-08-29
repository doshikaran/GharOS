"""Structural proof that E3's inbound-voice INFRASTRUCTURE agents (A63
Speech Recognition Handler, A66 Speaker Identification, A69 Voice Response
Agent — `backend/app/voice/`) hold no import path to the arbitration/
action-execution layer and construct no gated tool — the other,
independently-true half of safety invariant 8 (PHASES.md Phase 13,
ADR-020 Decision 5).

**`session_manager.py`, `routing.py` (both A62), and `session_types.py`
are the deliberate exception** — ADR-020 Decision 5 item 3 names A62 as
"the ONE module in this whole voice subsystem that holds an
`ApprovalGate` reference" (concretely, `routing.py` — see that module's
own docstring for why the R-tier gating logic was split out of
`session_manager.py`). All three are explicitly excluded from this scan
below; their own, separate structural guarantee (never calling `approve_
and_execute` for an R3-tier intent) is proven directly in `test_voice_
session_manager.py::TestR3NeverApprovedByVoiceAlone`.

Mirrors `app.agents.voice`'s own `test_voice_agents_arbitration_
boundary.py` AST-based technique exactly, scoped to this package's own
three infrastructure agents plus their shared support modules
(`types.py`, `errors.py`, `pacing.py`, `tts_client.py`).
"""

from __future__ import annotations

import ast
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_VOICE_INFRA_ROOT = _BACKEND_ROOT / "app" / "voice"

_EXCLUDED_FILENAMES = {"session_manager.py", "routing.py", "session_types.py", "__init__.py"}
"""`__init__.py` carries only the package docstring (no imports of its
own to check) — excluded for the same reason `test_voice_agents_
arbitration_boundary.py` doesn't need to special-case E2's own
`__init__.py` (it also has none)."""

_FORBIDDEN_IMPORT_SUBSTRINGS = (
    "app.arbitration",
    "arbitration.actions",
    "arbitration.gated_tool",
    "arbitration.approval_gate",
)


def _iter_scanned_files(root: Path) -> list[Path]:
    return sorted(
        p for p in root.glob("*.py") if "__pycache__" not in p.parts and p.name not in _EXCLUDED_FILENAMES
    )


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


class TestVoiceInfraRootExists:
    def test_voice_infra_root_exists(self) -> None:
        assert _VOICE_INFRA_ROOT.is_dir(), f"expected {_VOICE_INFRA_ROOT} to exist"

    def test_the_deliberate_exception_files_actually_exist(self) -> None:
        """Guards against this test silently "passing" because A62 was
        renamed/moved and the exclusion list above just never matches
        anything real."""
        assert (_VOICE_INFRA_ROOT / "session_manager.py").is_file()
        assert (_VOICE_INFRA_ROOT / "session_types.py").is_file()

    def test_scan_actually_covers_the_three_infra_agents(self) -> None:
        scanned_names = {p.name for p in _iter_scanned_files(_VOICE_INFRA_ROOT)}
        expected_files = (
            "speech_recognition_handler.py",
            "speaker_identification.py",
            "voice_response_agent.py",
        )
        for expected in expected_files:
            assert expected in scanned_names, f"expected {expected} to be part of this scan"


class TestNoVoiceInfraAgentImportsArbitration:
    def test_no_module_imports_arbitration(self) -> None:
        violations: list[str] = []
        for path in _iter_scanned_files(_VOICE_INFRA_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for module_name in _imported_module_names(tree):
                if any(substring in module_name for substring in _FORBIDDEN_IMPORT_SUBSTRINGS):
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} imports {module_name!r}")
        assert violations == [], (
            "inbound-voice infrastructure agents (A63/A66/A69) must have no import path to the "
            "arbitration/action-execution layer:\n" + "\n".join(violations)
        )

    def test_no_module_imports_a_gated_tool_name(self) -> None:
        forbidden_names = {"ApprovalGatedTool", "GATED_TIERS"}
        violations: list[str] = []
        for path in _iter_scanned_files(_VOICE_INFRA_ROOT):
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
            "no inbound-voice infrastructure agent should import ApprovalGatedTool/GATED_TIERS "
            "from contracts.tools:\n" + "\n".join(violations)
        )


class TestNoVoiceInfraAgentConstructsAToolRegistry:
    """A63/A66/A69 classify, compare, and speak — none of them acts, and
    none of them needs a `ToolRegistry` of any kind."""

    def test_no_module_constructs_a_tool_registry(self) -> None:
        violations: list[str] = []
        for path in _iter_scanned_files(_VOICE_INFRA_ROOT):
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for name in _call_function_names(tree):
                if name == "ToolRegistry":
                    violations.append(f"{path.relative_to(_BACKEND_ROOT)} constructs a ToolRegistry")
        assert violations == [], (
            "no inbound-voice infrastructure agent should hold any tool at all:\n" + "\n".join(violations)
        )
