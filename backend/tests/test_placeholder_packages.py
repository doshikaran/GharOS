"""`app.graph`, `app.audit`, `app.solvers` carried no logic in Phase 0
(placeholders only). Phase 1 fills `app.graph` and `app.audit` in for
real; `app.solvers` still carries no standalone logic of its own this
phase (its Phase-1-relevant pieces live in `app.graph` /
`app.persistence` — see that package's docstring) but must still import
cleanly and document why. This module proves both: the two now-real
packages expose their expected public classes, and all three remain
valid, importable Python packages with a phase-ownership docstring.
"""

from __future__ import annotations

import importlib


def test_all_three_packages_import_and_document_their_phase() -> None:
    for module_name in ("app.graph", "app.audit", "app.solvers"):
        module = importlib.import_module(module_name)
        assert module.__doc__ is not None
        assert "Phase" in module.__doc__


def test_app_graph_exposes_every_repository_implementation() -> None:
    from app.graph.decision_repository import FirestoreDecisionRepository
    from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
    from app.graph.obligation_repository import FirestoreObligationRepository
    from app.graph.pattern_repository import FirestorePatternRepository
    from app.graph.person_repository import FirestorePersonRepository
    from app.graph.reader import FirestoreGraphReader
    from app.graph.writer import FirestoreGraphWriter

    assert FirestoreGraphReader is not None
    assert FirestoreGraphWriter is not None
    assert FirestorePersonRepository is not None
    assert FirestoreObligationRepository is not None
    assert FirestoreDecisionRepository is not None
    assert FirestorePatternRepository is not None
    assert FirestoreGraphIntegrityChecker is not None


def test_app_audit_exposes_the_write_before_execute_machinery() -> None:
    from app.audit.audit_log import FirestoreAuditLog
    from app.audit.write_before_execute import AuditGuardedAction, write_before_execute

    assert FirestoreAuditLog is not None
    assert AuditGuardedAction is not None
    assert callable(write_before_execute)
