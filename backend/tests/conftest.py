"""Shared fixtures for Phase 1's Firestore-emulator-backed test suite.

**Every fixture here talks to the real Firestore emulator, never a mock**
(gharos-standards skill: "integration tests per subsystem against the
Firestore emulator — not mocks, the actual emulator"). `scripts/emulators.sh`
must be running (`FIRESTORE_EMULATOR_HOST`, default `localhost:8080`) before
running this suite — `firestore_client` fails fast with a clear message if
it isn't.

**Test isolation strategy:** each test function gets a `firestore.Client`
constructed with a fresh random project id. The Firestore emulator keeps a
fully separate in-memory database per project id, so this gives complete
inter-test isolation for free — no manual collection-clearing, no shared
state, no cross-test pollution — without needing a real GCP project or
`settings.gcp_project_id` (which is never read here on purpose: tests must
never be able to reach real Firestore even if a real project id happens to
be configured in `backend/.env`).
"""

from __future__ import annotations

import os
import socket
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    AgentId,
    Derivation,
    LanguageProfile,
    LiteracyMode,
    NodeId,
    Person,
    PersonRole,
    Provenance,
    SourceRef,
)
from google.cloud import firestore

from app.audit.audit_log import FirestoreAuditLog
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from seeds.demo_household import SeedResult
from seeds.seed_loader import load_demo_household

os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "localhost:8080")

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _assert_emulator_reachable() -> None:
    host = os.environ["FIRESTORE_EMULATOR_HOST"]
    host_name, _, port = host.partition(":")
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2.0)
        try:
            sock.connect((host_name, int(port)))
        except OSError as exc:
            raise RuntimeError(
                f"Firestore emulator not reachable at {host} — start it with "
                f"`scripts/emulators.sh` before running this test suite."
            ) from exc


@pytest.fixture
def firestore_client() -> Iterator[firestore.Client]:
    """A `firestore.Client` against a freshly-named, empty emulator
    project — never real Firestore (project id is always a random local
    test id, `settings.gcp_project_id` is never consulted here)."""
    _assert_emulator_reachable()
    project_id = f"gharos-test-{uuid.uuid4().hex[:16]}"
    client = firestore.Client(project=project_id, database="(default)")
    yield client
    client.close()  # type: ignore[no-untyped-call]


@pytest.fixture
def store(firestore_client: firestore.Client) -> FirestoreGraphStore:
    return FirestoreGraphStore(firestore_client)


@pytest.fixture
def writer(store: FirestoreGraphStore) -> FirestoreGraphWriter:
    return FirestoreGraphWriter(store)


@pytest.fixture
def reader(store: FirestoreGraphStore) -> FirestoreGraphReader:
    return FirestoreGraphReader(store)


@pytest.fixture
def audit_log(firestore_client: firestore.Client) -> FirestoreAuditLog:
    return FirestoreAuditLog(firestore_client)


@pytest.fixture
def idempotency_store(firestore_client: firestore.Client) -> FirestoreIdempotencyStore:
    return FirestoreIdempotencyStore(firestore_client)


@pytest.fixture
def seeded(store: FirestoreGraphStore, writer: FirestoreGraphWriter) -> SeedResult:
    """Loads the full demo household (`seeds.demo_household`) into a fresh
    emulator project via the real provenance-guarded writer. Returns the
    `SeedResult` so tests can reference specific seeded node/edge ids."""
    return load_demo_household(writer)


# ---------------------------------------------------------------------------
# Small provenance/person builders reused across test modules
# ---------------------------------------------------------------------------


def make_provenance(*, derivation: Derivation = Derivation.EXTRACTED, confidence: float = 0.9) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=(
            None
            if derivation is Derivation.AMBIGUOUS
            else SourceRef(source_document_id=NodeId("doc-1"), region="p1")
        ),
        confidence=confidence,
        deriving_agent=AgentId("A0"),
        created_at=NOW,
    )


def make_language_profile() -> LanguageProfile:
    return LanguageProfile(
        primary_language="hi",
        languages_understood=("hi", "en"),
        script_preference="devanagari",
        code_mixing_profile="hi-en",
        formality_preference="informal",
        literacy_mode=LiteracyMode.BOTH,
    )


def make_person(
    node_id: str,
    display_name: str,
    *,
    aliases: tuple[str, ...] = (),
    can_drive: bool = False,
    can_sign: bool = False,
    has_bank_access: bool = False,
    contact_channels: tuple[str, ...] = (),
) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=make_provenance(),
        display_name=display_name,
        aliases=aliases,
        role=PersonRole.ADULT,
        can_drive=can_drive,
        can_sign=can_sign,
        has_bank_access=has_bank_access,
        has_medical_proxy=False,
        contact_channels=contact_channels,
        language_profile=make_language_profile(),
    )


__all__ = ["NOW", "make_language_profile", "make_person", "make_provenance"]
