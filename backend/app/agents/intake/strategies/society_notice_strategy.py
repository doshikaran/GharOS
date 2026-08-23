"""`ExtractionStrategy` for `document_type_ids.SOCIETY_NOTICE` (spec §5.4.2).

Always produces one OBLIGATION (respond to / comply with the notice) with
a `states` edge from the source. Conditionally produces a `LEDGER_EVENT`
(when `amount` was extracted — dues notices) with an `owed_to` edge, and a
CONSTRAINT (when `notice_type` indicates a rule change) — matching the
spec's own conditional phrasing ("LEDGER_EVENT (if dues)", "CONSTRAINT (if
a rule change)").

**Scope boundary:** a rule-change CONSTRAINT is produced without any
`constrains` edges — this strategy has no household member list (only
`extracted_fields`), so it cannot know *which* PERSON(s) a household-wide
rule applies to. A downstream agent with graph access attaches those.
"""

from __future__ import annotations

from contracts.graph_types import (
    AgentId,
    Constraint,
    ConstraintKind,
    ConstraintSeverity,
    Edge,
    EdgeType,
    ExtractedField,
    GraphMappingResult,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
)

from ....adapters import document_type_ids as type_id
from ._common import (
    as_float,
    as_str,
    field_by_name,
    new_edge_id,
    new_node_id,
    parse_date_value,
    provenance_for,
    slugify,
)
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.SOCIETY_NOTICE
_RULE_CHANGE_MARKERS = ("rule", "policy")


class SocietyNoticeExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        society_field = field_by_name(extracted_fields, "society_name")
        notice_type_field = field_by_name(extracted_fields, "notice_type")

        society_name = as_str(society_field.value) if society_field is not None else None
        notice_type = as_str(notice_type_field.value) if notice_type_field is not None else None
        if society_name is None or notice_type is None or notice_type_field is None:
            missing = [
                n for n, v in (("society_name", society_name), ("notice_type", notice_type)) if v is None
            ]
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))

        due_date_field = field_by_name(extracted_fields, "due_date")
        due_date = parse_date_value(due_date_field.value) if due_date_field is not None else None

        obligation_id = new_node_id("obligation")
        obligation_provenance = provenance_for(
            notice_type_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        obligation = Obligation(
            id=obligation_id,
            provenance=obligation_provenance,
            title=f"Respond to {society_name} notice: {notice_type}",
            obligation_type="society_notice_response",
            due_at=due_date,
            must_start_by=None,
            effort_estimate_minutes=None,
            status=ObligationStatus.DERIVED,
            stated_or_implied=ObligationDerivation.STATED,
        )
        nodes: list[object] = [obligation]
        edges: list[Edge] = [
            Edge(
                id=new_edge_id(),
                provenance=obligation_provenance,
                edge_type=EdgeType.STATES,
                from_id=source_document_id,
                to_id=obligation_id,
            )
        ]

        amount_field = field_by_name(extracted_fields, "amount")
        amount = as_float(amount_field.value) if amount_field is not None else None
        if amount is not None and amount_field is not None:
            ledger_provenance = provenance_for(
                amount_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            )
            ledger_event_id = new_node_id("ledger_event")
            ledger_event = LedgerEvent(
                id=ledger_event_id,
                provenance=ledger_provenance,
                kind=LedgerEventKind.DUE,
                amount=amount,
                currency="INR",
                occurred_at=due_date or obligation_provenance.created_at,
                counterparty_raw=society_name,
            )
            nodes.append(ledger_event)
            edges.append(
                Edge(
                    id=new_edge_id(),
                    provenance=ledger_provenance,
                    edge_type=EdgeType.OWED_TO,
                    from_id=ledger_event_id,
                    to_id=NodeId(f"vendor:{slugify(society_name)}"),
                )
            )

        if any(marker in notice_type.lower() for marker in _RULE_CHANGE_MARKERS):
            constraint = Constraint(
                id=new_node_id("constraint"),
                provenance=obligation_provenance,
                kind=ConstraintKind.LEGAL,
                severity=ConstraintSeverity.SOFT,
                validity_start=None,
                validity_end=None,
                structured={"source": "society_notice", "notice_type": notice_type},
                original_text=notice_type,
            )
            nodes.append(constraint)

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["SocietyNoticeExtractionStrategy"]
