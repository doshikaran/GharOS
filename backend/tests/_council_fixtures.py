"""Shared, non-test fixture builders for the Household Council test suite
(A41-A49, `app.agents.council`) — mirrors `_gemini_fakes.py`/
`_fake_graph_reader.py`'s established "shared non-test helper living in
`backend/tests/`" pattern (no `test_*` name, never collected by pytest).

Every node builder here uses `Derivation.AMBIGUOUS`/`source_ref=None` by
default (these fixtures stand in for real household entities already on
the graph, exactly `test_path_simulator_agent.py`'s own `_provenance()`
convention) unless a caller overrides `derivation`.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Derivation,
    LanguageProfile,
    LedgerEvent,
    LedgerEventKind,
    LiteracyMode,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Person,
    PersonRole,
    Provenance,
    RecurringCommitment,
    SourceDocument,
)
from contracts.repositories import GraphReader

from app.agents.council.types import CandidateBranch
from app.graph.scoped_reader import GraphSubgraphScope, ScopedGraphReader

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def provenance(*, derivation: Derivation = Derivation.AMBIGUOUS, confidence: float = 0.9) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=None,
        confidence=confidence,
        deriving_agent=AgentId("A0"),
        created_at=NOW,
    )


def language_profile() -> LanguageProfile:
    return LanguageProfile(
        primary_language="en",
        languages_understood=("en",),
        script_preference="latin",
        code_mixing_profile=None,
        formality_preference=None,
        literacy_mode=LiteracyMode.TEXT_CAPABLE,
    )


def person(
    node_id: str,
    display_name: str,
    *,
    role: PersonRole = PersonRole.ADULT,
    has_medical_proxy: bool = False,
    can_drive: bool = True,
) -> Person:
    return Person(
        id=NodeId(node_id),
        provenance=provenance(),
        display_name=display_name,
        aliases=(),
        role=role,
        can_drive=can_drive,
        can_sign=True,
        has_bank_access=False,
        has_medical_proxy=has_medical_proxy,
        contact_channels=(),
        language_profile=language_profile(),
    )


def constraint(
    node_id: str,
    *,
    kind: ConstraintKind,
    severity: ConstraintSeverity = ConstraintSeverity.SOFT,
    original_text: str,
    structured: dict[str, str] | None = None,
) -> Constraint:
    return Constraint(
        id=NodeId(node_id),
        provenance=provenance(),
        kind=kind,
        severity=severity,
        validity_start=None,
        validity_end=None,
        structured=structured or {},
        original_text=original_text,
    )


def obligation(node_id: str, title: str, *, obligation_type: str = "logistics") -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=provenance(),
        title=title,
        obligation_type=obligation_type,
        due_at=None,
        must_start_by=None,
        effort_estimate_minutes=None,
        status=ObligationStatus.ASSIGNED,
        stated_or_implied=ObligationDerivation.STATED,
    )


def ledger_event(
    node_id: str, *, amount: float = 1000.0, counterparty_raw: str = "Test Merchant"
) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(node_id),
        provenance=provenance(),
        kind=LedgerEventKind.DEBIT,
        amount=amount,
        currency="INR",
        occurred_at=NOW,
        counterparty_raw=counterparty_raw,
    )


def recurring_commitment(node_id: str, *, label: str = "School fees") -> RecurringCommitment:
    return RecurringCommitment(
        id=NodeId(node_id),
        provenance=provenance(),
        label=label,
        counterparty="Test School",
        amount=5000.0,
        cadence="monthly",
        price_history=(),
        last_used_at=None,
        status="active",
    )


def source_document(node_id: str, *, document_type: str = "society_notice") -> SourceDocument:
    return SourceDocument(
        id=NodeId(node_id),
        provenance=provenance(),
        channel="email",
        raw_payload_ref="ref-1",
        document_type=document_type,
        ingested_at=NOW,
        original_language="en",
    )


def outcome(
    node_id: str, *, predicted: str, actual: str, variance: float | None, attribution_tags: tuple[str, ...]
) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=provenance(),
        predicted=predicted,
        actual=actual,
        variance=variance,
        attribution_tags=attribution_tags,
    )


def candidate_branch(
    branch_id: str, label: str, description: str, *, related_node_ids: tuple[str, ...] = ()
) -> CandidateBranch:
    return CandidateBranch(
        branch_id=NodeId(branch_id),
        label=label,
        description=description,
        related_node_ids=tuple(NodeId(n) for n in related_node_ids),
    )


def scoped(reader: GraphReader, scope: GraphSubgraphScope) -> ScopedGraphReader:
    """Small typing convenience — every call site in this test suite reads
    identically regardless of which of the five scope constants it passes."""
    return ScopedGraphReader(reader=reader, scope=scope)


__all__ = [
    "NOW",
    "candidate_branch",
    "constraint",
    "language_profile",
    "ledger_event",
    "obligation",
    "outcome",
    "person",
    "provenance",
    "recurring_commitment",
    "scoped",
    "source_document",
]
