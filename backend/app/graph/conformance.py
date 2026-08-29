"""Structural protocol conformance, enforced by `mypy --strict`.

`contracts/repositories.py`'s protocols are not `@runtime_checkable`
(deliberately — they carry no ABC machinery, and the CTO owns that
decision), so `isinstance(concrete_repo, SomeProtocol)` is not available as
a conformance check (gharos-standards skill's suggested "isinstance ... or
the structural equivalent"). The functions below are that structural
equivalent: each one's return type annotation is a `contracts.repositories`
protocol, and each one returns a concrete class from this package. If a
concrete class's method signatures ever drift from its protocol, `mypy
--strict app` fails here — this module has no other purpose and is never
called at runtime.
"""

from __future__ import annotations

from contracts.repositories import (
    DecisionRepository,
    GraphIntegrityChecker,
    GraphReader,
    GraphWriter,
    ObligationRepository,
    PatternRepository,
    PersonRepository,
)

from app.graph.decision_repository import FirestoreDecisionRepository
from app.graph.integrity_checker import FirestoreGraphIntegrityChecker
from app.graph.obligation_repository import FirestoreObligationRepository
from app.graph.pattern_repository import FirestorePatternRepository
from app.graph.person_repository import FirestorePersonRepository
from app.graph.reader import FirestoreGraphReader
from app.graph.scoped_reader import FINANCE_SCOPE, ScopedGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore


def _graph_reader_conforms(store: FirestoreGraphStore) -> GraphReader:
    return FirestoreGraphReader(store)


def _scoped_graph_reader_conforms(store: FirestoreGraphStore) -> GraphReader:
    """`ScopedGraphReader` (Phase 12, ADR-019) wraps any `GraphReader` and
    must itself structurally satisfy the same Protocol — any one scope
    constant proves the wrapper's own shape, since the scope only affects
    runtime filtering/denial, never the method signatures checked here."""
    return ScopedGraphReader(reader=FirestoreGraphReader(store), scope=FINANCE_SCOPE)


def _graph_writer_conforms(store: FirestoreGraphStore) -> GraphWriter:
    return FirestoreGraphWriter(store)


def _person_repository_conforms(store: FirestoreGraphStore) -> PersonRepository:
    return FirestorePersonRepository(store)


def _obligation_repository_conforms(store: FirestoreGraphStore) -> ObligationRepository:
    return FirestoreObligationRepository(store)


def _decision_repository_conforms(store: FirestoreGraphStore) -> DecisionRepository:
    return FirestoreDecisionRepository(store)


def _pattern_repository_conforms(store: FirestoreGraphStore) -> PatternRepository:
    return FirestorePatternRepository(store)


def _graph_integrity_checker_conforms(store: FirestoreGraphStore) -> GraphIntegrityChecker:
    return FirestoreGraphIntegrityChecker(store)
