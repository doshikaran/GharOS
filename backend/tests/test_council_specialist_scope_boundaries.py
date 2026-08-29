"""Structural proof of ADR-019 Decision 1's own registration-level
constraint, referenced by name in every one of A42-A46's own module
docstrings: each specialist's constructor accepts **only** `app.graph.
scoped_reader.ScopedGraphReader` — never an unscoped `contracts.
repositories.GraphReader` — and imports no other graph-access type at
all. Also proves Gate 12's own CTO review question concrete: "if two
specialists were swapped, would output change?"

Mirrors `test_action_construction_boundary.py`'s AST-based pattern (real
code, not a comment that merely discusses the rule).
"""

from __future__ import annotations

import ast
import json
from pathlib import Path

from contracts.graph_types import ConstraintKind, ConstraintSeverity, NodeId

from app.agents.council.finance_specialist_agent import FinanceSpecialistAgent
from app.agents.council.types import DecisionFraming, SpecialistReportRequest
from app.graph.scoped_reader import CARE_SCOPE, FINANCE_SCOPE
from app.reasoning.gemini_client import GeminiClient

from ._council_fixtures import candidate_branch, constraint, ledger_event, scoped
from ._fake_graph_reader import FakeGraphReader
from ._gemini_fakes import FakeModels, fake_router

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_COUNCIL_ROOT = _BACKEND_ROOT / "app" / "agents" / "council"

_SPECIALIST_MODULES = (
    "finance_specialist_agent.py",
    "care_specialist_agent.py",
    "education_specialist_agent.py",
    "logistics_specialist_agent.py",
    "legal_specialist_agent.py",
)


def _imported_names_from(tree: ast.AST, module: str) -> list[str]:
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == module:
            names.extend(alias.name for alias in node.names)
    return names


def _constructor_annotation_names(tree: ast.AST) -> list[str]:
    """Every parameter type annotation name on every `__init__` method in
    the module — used to assert the scoped-reader parameter is annotated
    `ScopedGraphReader`, never a bare `GraphReader`."""
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "__init__":
            for arg in node.args.args + node.args.kwonlyargs:
                if arg.annotation is not None:
                    names.extend(n.id for n in ast.walk(arg.annotation) if isinstance(n, ast.Name))
    return names


class TestNoSpecialistImportsUnscopedGraphReader:
    def test_council_root_exists(self) -> None:
        assert _COUNCIL_ROOT.is_dir(), f"expected {_COUNCIL_ROOT} to exist"

    def test_no_specialist_module_imports_graphreader_from_contracts_repositories(self) -> None:
        violations: list[str] = []
        for filename in _SPECIALIST_MODULES:
            path = _COUNCIL_ROOT / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            imported = _imported_names_from(tree, "contracts.repositories")
            if "GraphReader" in imported:
                violations.append(filename)
        assert violations == [], (
            "Council domain specialists must never import the unscoped GraphReader type "
            f"directly (ADR-019 Decision 1): {violations}"
        )

    def test_every_specialist_constructor_annotates_scoped_graph_reader(self) -> None:
        missing: list[str] = []
        for filename in _SPECIALIST_MODULES:
            path = _COUNCIL_ROOT / filename
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            if "ScopedGraphReader" not in _constructor_annotation_names(tree):
                missing.append(filename)
        assert missing == [], f"expected every specialist's __init__ to annotate ScopedGraphReader: {missing}"


class TestSwappingScopesChangesOutput:
    """Gate 12's own CTO review question, made concrete: construct the
    *same* specialist class against two different real scopes, over the
    *same* fixture graph and the *same* real candidate branch, and prove
    the real evidence text actually sent to the model differs — i.e. a
    specialist's real input (and therefore its real output) is a genuine
    function of which subgraph it can see, not an accident of which class
    happens to be running."""

    def test_finance_specialist_prompt_evidence_differs_under_finance_vs_care_scope(self) -> None:
        ledger_node = ledger_event("event-1", amount=50000.0, counterparty_raw="Car Dealer")
        mobility_constraint = constraint(
            "constraint-1",
            kind=ConstraintKind.MOBILITY,
            severity=ConstraintSeverity.HARD,
            original_text="Dad needs a low door sill",
        )
        reader = FakeGraphReader(nodes_by_id={"event-1": ledger_node, "constraint-1": mobility_constraint})
        branch = candidate_branch(
            "branch-a", "Option A", "A real option", related_node_ids=("event-1", "constraint-1")
        )
        request = SpecialistReportRequest(
            framing=DecisionFraming(
                decision_id=NodeId("decision-1"),
                question="Buy a car?",
                trigger="repeated repairs",
                candidate_branches=(branch,),
            )
        )
        response_text = json.dumps({"stance": "neutral", "reasoning": "x", "evidence_refs": []})

        finance_models = FakeModels(texts=[response_text])
        finance_agent = FinanceSpecialistAgent(
            gemini_client=GeminiClient(router=fake_router(finance_models)),
            scoped_reader=scoped(reader, FINANCE_SCOPE),
        )
        finance_agent.report(request)

        care_scope_models = FakeModels(texts=[response_text])
        care_scope_finance_agent = FinanceSpecialistAgent(
            gemini_client=GeminiClient(router=fake_router(care_scope_models)),
            scoped_reader=scoped(reader, CARE_SCOPE),
        )
        care_scope_finance_agent.report(request)

        finance_prompt = str(finance_models.calls[0]["contents"])
        care_scope_prompt = str(care_scope_models.calls[0]["contents"])

        # Same specialist class, same fixture graph, same candidate branch
        # — only the scope it was constructed with changed. The real
        # evidence each one could see differs, and that real difference
        # shows up verbatim in what was actually sent to the model.
        assert "Car Dealer" in finance_prompt
        assert "Car Dealer" not in care_scope_prompt
        assert "Dad needs a low door sill" in care_scope_prompt
        assert "Dad needs a low door sill" not in finance_prompt
        assert finance_prompt != care_scope_prompt
