"""Round-trip tests for every node-type codec (`app.persistence.codecs`)
and the collection registry — Gate 1: "every node and edge type
round-trips (write, read back, values match)".

These tests exercise the codecs directly (no Firestore I/O) — full
write/read round trips against the real emulator are proven in
`test_traversals.py` and `test_versioning.py`, which cover every node type
indirectly via the seeded household. This module is the exhaustive,
fast, per-type check that encode->decode is lossless for all 17 types.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.graph_types import (
    ActionRecord,
    AgentId,
    ApprovalRequest,
    ApprovalStatus,
    AttendanceRecord,
    Branch,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    CouncilPosition,
    Decision,
    DecisionStatus,
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
    Pattern,
    Person,
    PersonRole,
    Provenance,
    Provider,
    PurchaseItem,
    RecurringCommitment,
    SourceDocument,
    SourceRef,
    Vendor,
)

from app.persistence.codecs.nodes import NODE_CODECS, decode_node, encode_node
from app.persistence.collections import NODE_TYPE_TO_COLLECTION

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


def _prov(
    *, derivation: Derivation = Derivation.EXTRACTED, source_ref: SourceRef | None = None
) -> Provenance:
    return Provenance(
        derivation=derivation,
        source_ref=source_ref
        if source_ref is not None
        else SourceRef(source_document_id=NodeId("doc-1"), region="p1"),
        confidence=0.83,
        deriving_agent=AgentId("A7"),
        created_at=NOW,
        superseded_at=None,
    )


LANG = LanguageProfile(
    primary_language="hi",
    languages_understood=("hi", "en"),
    script_preference="devanagari",
    code_mixing_profile="hi-en",
    formality_preference="informal",
    literacy_mode=LiteracyMode.BOTH,
)


def _all_sample_nodes() -> list[object]:
    return [
        Person(
            id=NodeId("n-person"),
            provenance=_prov(),
            display_name="Priya",
            aliases=("Priya Sharma", "Mom"),
            role=PersonRole.ADULT,
            can_drive=True,
            can_sign=True,
            has_bank_access=True,
            has_medical_proxy=False,
            contact_channels=("whatsapp:+91-1",),
            language_profile=LANG,
            voiceprint_ref="voice-1",
            pronunciation_hints="PREE-ya",
        ),
        Constraint(
            id=NodeId("n-constraint"),
            provenance=_prov(),
            kind=ConstraintKind.DIETARY,
            severity=ConstraintSeverity.HARD,
            validity_start=NOW,
            validity_end=None,
            structured={"allergen": "nut"},
            original_text="no nuts, ever",
        ),
        Obligation(
            id=NodeId("n-obligation"),
            provenance=_prov(),
            title="Pay maintenance",
            obligation_type="payment",
            due_at=NOW,
            must_start_by=NOW,
            effort_estimate_minutes=10,
            status=ObligationStatus.ASSIGNED,
            stated_or_implied=ObligationDerivation.STATED,
        ),
        LedgerEvent(
            id=NodeId("n-ledger"),
            provenance=_prov(),
            kind=LedgerEventKind.DEBIT,
            amount=2500.0,
            currency="INR",
            occurred_at=NOW,
            counterparty_raw="SOCIETY",
        ),
        RecurringCommitment(
            id=NodeId("n-commitment"),
            provenance=_prov(),
            label="Society maintenance",
            counterparty="Sunrise Society",
            amount=2500.0,
            cadence="monthly",
            price_history=((NOW, 2500.0), (NOW, 2300.0)),
            last_used_at=NOW,
            status="active",
        ),
        Vendor(
            id=NodeId("n-vendor"),
            provenance=_prov(),
            category="housing",
            contacts=("a@b.example",),
            reliability_score=0.9,
            response_latency_hours=24.0,
        ),
        Provider(
            id=NodeId("n-provider"),
            provenance=_prov(),
            name="Dr Mehta",
            category="medical",
            rating=4.5,
            distance_km=1.2,
            availability_notes="9-9",
            price_band="$$",
            specialisations=("pediatrics",),
        ),
        Decision(
            id=NodeId("n-decision"),
            provenance=_prov(),
            question="Renew or buy?",
            trigger="lease expiring",
            status=DecisionStatus.RESOLVED,
            resolution_summary="Renew",
            rationale="cheaper",
        ),
        Branch(
            id=NodeId("n-branch"),
            provenance=_prov(),
            decision_id=NodeId("n-decision"),
            label="Renew",
            projected_impacts={"cost": "low"},
            grounding_refs=("doc-1",),
            critiques=("risk: none",),
        ),
        CouncilPosition(
            id=NodeId("n-position"),
            provenance=_prov(),
            decision_id=NodeId("n-decision"),
            held_by_agent=AgentId("A42"),
            stance="supports",
            branch_id=NodeId("n-branch"),
            reasoning="cheaper",
            evidence_refs=("doc-1",),
        ),
        Outcome(
            id=NodeId("n-outcome"),
            provenance=_prov(),
            predicted="on time",
            actual="on time",
            variance=0.0,
            attribution_tags=("on-time",),
        ),
        SourceDocument(
            id=NodeId("n-source-doc"),
            provenance=_prov(),
            channel="email",
            raw_payload_ref="emails/1.eml",
            document_type="SOCIETY_HOA_NOTICE",
            ingested_at=NOW,
            original_language="en",
        ),
        ActionRecord(
            id=NodeId("n-action-record"),
            provenance=_prov(),
            action_type="send_message",
            executed_at=NOW,
            approved_by=NodeId("n-person"),
        ),
        ApprovalRequest(
            id=NodeId("n-approval-request"),
            provenance=_prov(),
            proposed_action_summary="Send payment",
            evidence_bundle={"reason": "due today"},
            risk_tier="R3",
            confidence=0.9,
            consequence_if_wrong="late fee",
            status=ApprovalStatus.PENDING,
            expires_at=NOW,
        ),
        PurchaseItem(
            id=NodeId("n-purchase-item"),
            provenance=_prov(),
            ledger_event_id=NodeId("n-ledger"),
            description="Bread",
            normalized_category="groceries",
            quantity=1.0,
            unit_price=90.0,
            line_total=90.0,
        ),
        Pattern(
            id=NodeId("n-pattern"),
            provenance=_prov(derivation=Derivation.AMBIGUOUS, source_ref=None),
            description="Grocery runs done by Priya",
            support_count=3,
            contributing_outcome_ids=(NodeId("n-outcome"),),
        ),
        AttendanceRecord(
            id=NodeId("n-attendance-record"),
            provenance=_prov(),
            staff_person_id=NodeId("n-person"),
            month="2026-08",
            days_present=22,
            days_absent=2,
            days_on_leave=1,
            total_days_in_period=25,
            daily_marks={"01": "present", "02": "absent", "03": "leave"},
            advance_notations=("₹2,000 advance noted in margin, 12 Aug",),
        ),
    ]


class TestNodeTypeRegistryCompleteness:
    def test_every_node_type_has_a_codec_and_a_collection(self) -> None:
        assert set(NODE_CODECS.keys()) == set(NODE_TYPE_TO_COLLECTION.keys())

    def test_seventeen_node_types_are_registered(self) -> None:
        assert len(NODE_TYPE_TO_COLLECTION) == 17


class TestNodeRoundTrip:
    @pytest.mark.parametrize("node", _all_sample_nodes(), ids=lambda n: type(n).__name__)
    def test_encode_decode_round_trips(self, node: object) -> None:
        data = encode_node(node)
        decoded = decode_node(type(node), str(node.id), data)  # type: ignore[attr-defined]
        assert decoded == node

    def test_encode_is_firestore_safe_types_only(self) -> None:
        """No tuples, no Enum members, no nested dataclass instances survive
        into the encoded dict — Firestore rejects tuples and doesn't know
        how to serialize an Enum or a dataclass."""
        for node in _all_sample_nodes():
            data = encode_node(node)
            _assert_firestore_safe(data)


def _assert_firestore_safe(value: object) -> None:
    if isinstance(value, dict):
        for v in value.values():
            _assert_firestore_safe(v)
    elif isinstance(value, list):
        for v in value:
            _assert_firestore_safe(v)
    elif isinstance(value, tuple):
        raise AssertionError(f"tuple leaked into encoded payload: {value!r}")
    elif value is None or isinstance(value, str | int | float | bool | datetime):
        pass
    else:
        raise AssertionError(f"non-Firestore-safe value leaked into encoded payload: {value!r}")
