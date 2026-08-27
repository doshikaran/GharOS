"""Encode/decode codecs for all 17 node types (spec §5.2).

Each node type gets an explicit `encode_*`/`decode_*` pair rather than a
reflective generic walk — `contracts.graph_types` uses `Literal[...]`,
`tuple[tuple[...], ...]`, and optional nested dataclasses that are not
safely reconstructible from runtime reflection alone under
`from __future__ import annotations` (string annotations). Explicit codecs
are also what make `test_serialization.py`'s per-type round-trip tests
possible to write clearly.

`NODE_CODECS` is the registry `FirestoreGraphStore` (and everything above
it) dispatches through — the *only* place a node type's collection name and
codec pair are joined.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, cast

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
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Pattern,
    Person,
    PersonRole,
    Provider,
    PurchaseItem,
    RecurringCommitment,
    SourceDocument,
    Vendor,
)

from app.persistence.codecs.common import (
    decode_language_profile,
    decode_provenance,
    encode_language_profile,
    encode_optional_datetime,
    encode_provenance,
    require_aware,
)


@dataclass(frozen=True, slots=True)
class NodeCodec[NodeT]:
    """One node type's encode/decode pair. `encode` never receives the
    Firestore document id (it *is* `node.id`); `decode` receives the
    Firestore document id explicitly and trusts it over any embedded `id`
    field, since the document key is the actual source of truth for
    identity once stored."""

    encode: Any
    decode: Any


def _recurring_status(value: str) -> Literal["active", "paused", "cancelled"]:
    if value not in ("active", "paused", "cancelled"):
        raise ValueError(f"invalid RecurringCommitment.status: {value!r}")
    return cast(Literal["active", "paused", "cancelled"], value)


def _council_stance(value: str) -> Literal["supports", "opposes", "neutral"]:
    if value not in ("supports", "opposes", "neutral"):
        raise ValueError(f"invalid CouncilPosition.stance: {value!r}")
    return cast(Literal["supports", "opposes", "neutral"], value)


# ---------------------------------------------------------------------------
# Person
# ---------------------------------------------------------------------------


def encode_person(node: Person) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "display_name": node.display_name,
        "aliases": list(node.aliases),
        "role": node.role.value,
        "can_drive": node.can_drive,
        "can_sign": node.can_sign,
        "has_bank_access": node.has_bank_access,
        "has_medical_proxy": node.has_medical_proxy,
        "contact_channels": list(node.contact_channels),
        "language_profile": encode_language_profile(node.language_profile),
        "voiceprint_ref": node.voiceprint_ref,
        "pronunciation_hints": node.pronunciation_hints,
    }


def decode_person(doc_id: str, data: dict[str, Any]) -> Person:
    return Person(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        display_name=data["display_name"],
        aliases=tuple(data["aliases"]),
        role=PersonRole(data["role"]),
        can_drive=data["can_drive"],
        can_sign=data["can_sign"],
        has_bank_access=data["has_bank_access"],
        has_medical_proxy=data["has_medical_proxy"],
        contact_channels=tuple(data["contact_channels"]),
        language_profile=decode_language_profile(data["language_profile"]),
        voiceprint_ref=data.get("voiceprint_ref"),
        pronunciation_hints=data.get("pronunciation_hints"),
    )


# ---------------------------------------------------------------------------
# Constraint
# ---------------------------------------------------------------------------


def encode_constraint(node: Constraint) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "kind": node.kind.value,
        "severity": node.severity.value,
        "validity_start": encode_optional_datetime(node.validity_start, field="validity_start"),
        "validity_end": encode_optional_datetime(node.validity_end, field="validity_end"),
        "structured": dict(node.structured),
        "original_text": node.original_text,
    }


def decode_constraint(doc_id: str, data: dict[str, Any]) -> Constraint:
    return Constraint(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        kind=ConstraintKind(data["kind"]),
        severity=ConstraintSeverity(data["severity"]),
        validity_start=data.get("validity_start"),
        validity_end=data.get("validity_end"),
        structured=dict(data["structured"]),
        original_text=data["original_text"],
    )


# ---------------------------------------------------------------------------
# Obligation
# ---------------------------------------------------------------------------


def encode_obligation(node: Obligation) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "title": node.title,
        "obligation_type": node.obligation_type,
        "due_at": encode_optional_datetime(node.due_at, field="due_at"),
        "must_start_by": encode_optional_datetime(node.must_start_by, field="must_start_by"),
        "effort_estimate_minutes": node.effort_estimate_minutes,
        "status": node.status.value,
        "stated_or_implied": node.stated_or_implied.value,
    }


def decode_obligation(doc_id: str, data: dict[str, Any]) -> Obligation:
    return Obligation(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        title=data["title"],
        obligation_type=data["obligation_type"],
        due_at=data.get("due_at"),
        must_start_by=data.get("must_start_by"),
        effort_estimate_minutes=data.get("effort_estimate_minutes"),
        status=ObligationStatus(data["status"]),
        stated_or_implied=ObligationDerivation(data["stated_or_implied"]),
    )


# ---------------------------------------------------------------------------
# LedgerEvent
# ---------------------------------------------------------------------------


def encode_ledger_event(node: LedgerEvent) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "kind": node.kind.value,
        "amount": node.amount,
        "currency": node.currency,
        "occurred_at": require_aware(node.occurred_at, field="occurred_at"),
        "counterparty_raw": node.counterparty_raw,
    }


def decode_ledger_event(doc_id: str, data: dict[str, Any]) -> LedgerEvent:
    return LedgerEvent(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        kind=LedgerEventKind(data["kind"]),
        amount=data["amount"],
        currency=data["currency"],
        occurred_at=data["occurred_at"],
        counterparty_raw=data["counterparty_raw"],
    )


# ---------------------------------------------------------------------------
# RecurringCommitment
# ---------------------------------------------------------------------------


def encode_recurring_commitment(node: RecurringCommitment) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "label": node.label,
        "counterparty": node.counterparty,
        "amount": node.amount,
        "cadence": node.cadence,
        "price_history": [
            {"at": require_aware(at, field="price_history.at"), "price": price}
            for at, price in node.price_history
        ],
        "last_used_at": encode_optional_datetime(node.last_used_at, field="last_used_at"),
        "status": node.status,
    }


def decode_recurring_commitment(doc_id: str, data: dict[str, Any]) -> RecurringCommitment:
    return RecurringCommitment(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        label=data["label"],
        counterparty=data["counterparty"],
        amount=data["amount"],
        cadence=data["cadence"],
        price_history=tuple((entry["at"], entry["price"]) for entry in data["price_history"]),
        last_used_at=data.get("last_used_at"),
        status=_recurring_status(data["status"]),
    )


# ---------------------------------------------------------------------------
# Vendor
# ---------------------------------------------------------------------------


def encode_vendor(node: Vendor) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "category": node.category,
        "contacts": list(node.contacts),
        "reliability_score": node.reliability_score,
        "response_latency_hours": node.response_latency_hours,
    }


def decode_vendor(doc_id: str, data: dict[str, Any]) -> Vendor:
    return Vendor(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        category=data["category"],
        contacts=tuple(data["contacts"]),
        reliability_score=data.get("reliability_score"),
        response_latency_hours=data.get("response_latency_hours"),
    )


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


def encode_provider(node: Provider) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "name": node.name,
        "category": node.category,
        "rating": node.rating,
        "distance_km": node.distance_km,
        "availability_notes": node.availability_notes,
        "price_band": node.price_band,
        "specialisations": list(node.specialisations),
    }


def decode_provider(doc_id: str, data: dict[str, Any]) -> Provider:
    return Provider(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        name=data["name"],
        category=data["category"],
        rating=data.get("rating"),
        distance_km=data.get("distance_km"),
        availability_notes=data.get("availability_notes"),
        price_band=data.get("price_band"),
        specialisations=tuple(data["specialisations"]),
    )


# ---------------------------------------------------------------------------
# Decision — permanent, never pruned
# ---------------------------------------------------------------------------


def encode_decision(node: Decision) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "question": node.question,
        "trigger": node.trigger,
        "status": node.status.value,
        "resolution_summary": node.resolution_summary,
        "rationale": node.rationale,
    }


def decode_decision(doc_id: str, data: dict[str, Any]) -> Decision:
    return Decision(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        question=data["question"],
        trigger=data["trigger"],
        status=DecisionStatus(data["status"]),
        resolution_summary=data.get("resolution_summary"),
        rationale=data.get("rationale"),
    )


# ---------------------------------------------------------------------------
# Branch
# ---------------------------------------------------------------------------


def encode_branch(node: Branch) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "decision_id": str(node.decision_id),
        "label": node.label,
        "projected_impacts": dict(node.projected_impacts),
        "grounding_refs": list(node.grounding_refs),
        "critiques": list(node.critiques),
    }


def decode_branch(doc_id: str, data: dict[str, Any]) -> Branch:
    return Branch(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        decision_id=NodeId(data["decision_id"]),
        label=data["label"],
        projected_impacts=dict(data["projected_impacts"]),
        grounding_refs=tuple(data["grounding_refs"]),
        critiques=tuple(data["critiques"]),
    )


# ---------------------------------------------------------------------------
# CouncilPosition
# ---------------------------------------------------------------------------


def encode_council_position(node: CouncilPosition) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "decision_id": str(node.decision_id),
        "held_by_agent": str(node.held_by_agent),
        "stance": node.stance,
        "branch_id": None if node.branch_id is None else str(node.branch_id),
        "reasoning": node.reasoning,
        "evidence_refs": list(node.evidence_refs),
    }


def decode_council_position(doc_id: str, data: dict[str, Any]) -> CouncilPosition:
    branch_id = data.get("branch_id")
    return CouncilPosition(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        decision_id=NodeId(data["decision_id"]),
        held_by_agent=AgentId(data["held_by_agent"]),
        stance=_council_stance(data["stance"]),
        branch_id=None if branch_id is None else NodeId(branch_id),
        reasoning=data["reasoning"],
        evidence_refs=tuple(data["evidence_refs"]),
    )


# ---------------------------------------------------------------------------
# Outcome
# ---------------------------------------------------------------------------


def encode_outcome(node: Outcome) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "predicted": node.predicted,
        "actual": node.actual,
        "variance": node.variance,
        "attribution_tags": list(node.attribution_tags),
    }


def decode_outcome(doc_id: str, data: dict[str, Any]) -> Outcome:
    return Outcome(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        predicted=data["predicted"],
        actual=data["actual"],
        variance=data.get("variance"),
        attribution_tags=tuple(data["attribution_tags"]),
    )


# ---------------------------------------------------------------------------
# SourceDocument
# ---------------------------------------------------------------------------


def encode_source_document(node: SourceDocument) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "channel": node.channel,
        "raw_payload_ref": node.raw_payload_ref,
        "document_type": node.document_type,
        "ingested_at": require_aware(node.ingested_at, field="ingested_at"),
        "original_language": node.original_language,
    }


def decode_source_document(doc_id: str, data: dict[str, Any]) -> SourceDocument:
    return SourceDocument(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        channel=data["channel"],
        raw_payload_ref=data["raw_payload_ref"],
        document_type=data.get("document_type"),
        ingested_at=data["ingested_at"],
        original_language=data.get("original_language"),
    )


# ---------------------------------------------------------------------------
# ActionRecord
# ---------------------------------------------------------------------------


def encode_action_record(node: ActionRecord) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "action_type": node.action_type,
        "executed_at": require_aware(node.executed_at, field="executed_at"),
        "approved_by": None if node.approved_by is None else str(node.approved_by),
    }


def decode_action_record(doc_id: str, data: dict[str, Any]) -> ActionRecord:
    approved_by = data.get("approved_by")
    return ActionRecord(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        action_type=data["action_type"],
        executed_at=data["executed_at"],
        approved_by=None if approved_by is None else NodeId(approved_by),
    )


# ---------------------------------------------------------------------------
# ApprovalRequest
# ---------------------------------------------------------------------------


def encode_approval_request(node: ApprovalRequest) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "proposed_action_summary": node.proposed_action_summary,
        "evidence_bundle": dict(node.evidence_bundle),
        "risk_tier": node.risk_tier,
        "confidence": node.confidence,
        "consequence_if_wrong": node.consequence_if_wrong,
        "status": node.status.value,
        "expires_at": require_aware(node.expires_at, field="expires_at"),
    }


def decode_approval_request(doc_id: str, data: dict[str, Any]) -> ApprovalRequest:
    return ApprovalRequest(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        proposed_action_summary=data["proposed_action_summary"],
        evidence_bundle=dict(data["evidence_bundle"]),
        risk_tier=data["risk_tier"],
        confidence=data["confidence"],
        consequence_if_wrong=data["consequence_if_wrong"],
        status=ApprovalStatus(data["status"]),
        expires_at=data["expires_at"],
    )


# ---------------------------------------------------------------------------
# PurchaseItem — the finest-grained evidence node in the system
# ---------------------------------------------------------------------------


def encode_purchase_item(node: PurchaseItem) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "ledger_event_id": str(node.ledger_event_id),
        "description": node.description,
        "normalized_category": node.normalized_category,
        "quantity": node.quantity,
        "unit_price": node.unit_price,
        "line_total": node.line_total,
    }


def decode_purchase_item(doc_id: str, data: dict[str, Any]) -> PurchaseItem:
    return PurchaseItem(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        ledger_event_id=NodeId(data["ledger_event_id"]),
        description=data["description"],
        normalized_category=data.get("normalized_category"),
        quantity=data.get("quantity"),
        unit_price=data.get("unit_price"),
        line_total=data["line_total"],
    )


# ---------------------------------------------------------------------------
# Pattern
# ---------------------------------------------------------------------------


def encode_pattern(node: Pattern) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "description": node.description,
        "support_count": node.support_count,
        "contributing_outcome_ids": [str(oid) for oid in node.contributing_outcome_ids],
    }


def decode_pattern(doc_id: str, data: dict[str, Any]) -> Pattern:
    return Pattern(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        description=data["description"],
        support_count=data["support_count"],
        contributing_outcome_ids=tuple(NodeId(oid) for oid in data["contributing_outcome_ids"]),
    )


# ---------------------------------------------------------------------------
# AttendanceRecord
# ---------------------------------------------------------------------------


def encode_attendance_record(node: AttendanceRecord) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "provenance": encode_provenance(node.provenance),
        "staff_person_id": str(node.staff_person_id),
        "month": node.month,
        "days_present": node.days_present,
        "days_absent": node.days_absent,
        "days_on_leave": node.days_on_leave,
        "total_days_in_period": node.total_days_in_period,
        "daily_marks": dict(node.daily_marks),
        "advance_notations": list(node.advance_notations),
    }


def decode_attendance_record(doc_id: str, data: dict[str, Any]) -> AttendanceRecord:
    return AttendanceRecord(
        id=NodeId(doc_id),
        provenance=decode_provenance(data["provenance"]),
        staff_person_id=NodeId(data["staff_person_id"]),
        month=data["month"],
        days_present=data["days_present"],
        days_absent=data["days_absent"],
        days_on_leave=data["days_on_leave"],
        total_days_in_period=data["total_days_in_period"],
        daily_marks=dict(data["daily_marks"]),
        advance_notations=tuple(data["advance_notations"]),
    )


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

NODE_CODECS: dict[type, NodeCodec[Any]] = {
    Person: NodeCodec(encode=encode_person, decode=decode_person),
    Constraint: NodeCodec(encode=encode_constraint, decode=decode_constraint),
    Obligation: NodeCodec(encode=encode_obligation, decode=decode_obligation),
    LedgerEvent: NodeCodec(encode=encode_ledger_event, decode=decode_ledger_event),
    RecurringCommitment: NodeCodec(encode=encode_recurring_commitment, decode=decode_recurring_commitment),
    Vendor: NodeCodec(encode=encode_vendor, decode=decode_vendor),
    Provider: NodeCodec(encode=encode_provider, decode=decode_provider),
    Decision: NodeCodec(encode=encode_decision, decode=decode_decision),
    Branch: NodeCodec(encode=encode_branch, decode=decode_branch),
    CouncilPosition: NodeCodec(encode=encode_council_position, decode=decode_council_position),
    Outcome: NodeCodec(encode=encode_outcome, decode=decode_outcome),
    SourceDocument: NodeCodec(encode=encode_source_document, decode=decode_source_document),
    ActionRecord: NodeCodec(encode=encode_action_record, decode=decode_action_record),
    ApprovalRequest: NodeCodec(encode=encode_approval_request, decode=decode_approval_request),
    PurchaseItem: NodeCodec(encode=encode_purchase_item, decode=decode_purchase_item),
    Pattern: NodeCodec(encode=encode_pattern, decode=decode_pattern),
    AttendanceRecord: NodeCodec(encode=encode_attendance_record, decode=decode_attendance_record),
}
"""One entry per node type in `contracts.graph_types` (spec §5.2). Keys must
match `app.persistence.collections.NODE_TYPE_TO_COLLECTION` exactly —
`test_serialization.py` asserts the two dicts have identical key sets."""


def encode_node(node: Any) -> dict[str, Any]:
    """Dispatches to the registered codec for `type(node)`.

    Raises:
        KeyError: `type(node)` is not a registered node type.
    """
    return NODE_CODECS[type(node)].encode(node)  # type: ignore[no-any-return]


def decode_node(node_type: type, doc_id: str, data: dict[str, Any]) -> Any:
    """Dispatches to the registered codec for `node_type`.

    Raises:
        KeyError: `node_type` is not a registered node type.
    """
    return NODE_CODECS[node_type].decode(doc_id, data)
