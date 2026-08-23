"""`ExtractionStrategy` for `document_type_ids.UTILITY_BILL` (spec §5.4.2).

**Registry inconsistency flagged, not worked around (per this phase's own
review discipline):** `document_type_specs.py`'s `_utility_bill_spec`
docstring says a payment OBLIGATION attaches to its SOURCE_DOCUMENT via a
`states` edge, but that spec entry's own `target_node_types` is
`("LEDGER_EVENT", "RECURRING_COMMITMENT")` — no `"OBLIGATION"` — while
`target_edge_types` does include `EdgeType.STATES` (whose only sensible
target per spec §5.3's edge table is an OBLIGATION). Since `OBLIGATION` is
not a declared target node type for this entry, this strategy does not
fabricate one merely to have somewhere to point a `states` edge — it
produces the `LEDGER_EVENT` (kind `DUE`) and `RECURRING_COMMITMENT` only,
with `belongs_to`/`owed_to` edges between them, and reports this
inconsistency to the CTO/E3 rather than silently inventing a node the
registry entry never declared. See this phase's final report.

Cadence for the `RECURRING_COMMITMENT` is computed deterministically from
`billing_period_start`/`billing_period_end` (real, extracted timestamps —
arithmetic over literal data, not a guess) rather than left unset.
"""

from __future__ import annotations

from contracts.graph_types import (
    AgentId,
    Edge,
    EdgeType,
    ExtractedField,
    GraphMappingResult,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
    RecurringCommitment,
)

from ....adapters import document_type_ids as type_id
from ._common import (
    as_float,
    as_str,
    cadence_from_period,
    field_by_name,
    new_edge_id,
    new_node_id,
    parse_date_value,
    provenance_for,
    slugify,
)
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.UTILITY_BILL


class UtilityBillExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        provider_field = field_by_name(extracted_fields, "provider")
        amount_field = field_by_name(extracted_fields, "amount_due")
        due_date_field = field_by_name(extracted_fields, "due_date")
        period_start_field = field_by_name(extracted_fields, "billing_period_start")
        period_end_field = field_by_name(extracted_fields, "billing_period_end")

        provider = as_str(provider_field.value) if provider_field is not None else None
        amount_due = as_float(amount_field.value) if amount_field is not None else None
        due_date = parse_date_value(due_date_field.value) if due_date_field is not None else None

        missing = [
            name
            for name, value in (("provider", provider), ("amount_due", amount_due), ("due_date", due_date))
            if value is None
        ]
        if missing:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert amount_field is not None
        assert provider is not None and amount_due is not None and due_date is not None

        ledger_event_id = new_node_id("ledger_event")
        ledger_provenance = provenance_for(
            amount_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        ledger_event = LedgerEvent(
            id=ledger_event_id,
            provenance=ledger_provenance,
            kind=LedgerEventKind.DUE,
            amount=amount_due,
            currency="INR",
            occurred_at=due_date,
            counterparty_raw=provider,
        )

        commitment_id = new_node_id("recurring_commitment")
        cadence = cadence_from_period(
            period_start_field.value if period_start_field else None,
            period_end_field.value if period_end_field else None,
        )
        commitment = RecurringCommitment(
            id=commitment_id,
            provenance=ledger_provenance,
            label=f"{provider} utility",
            counterparty=provider,
            amount=amount_due,
            cadence=cadence,
            price_history=((due_date, amount_due),),
            last_used_at=None,
            status="active",
        )

        vendor_id = NodeId(f"vendor:{slugify(provider)}")
        edges = [
            Edge(
                id=new_edge_id(),
                provenance=ledger_provenance,
                edge_type=EdgeType.BELONGS_TO,
                from_id=ledger_event_id,
                to_id=commitment_id,
            ),
            Edge(
                id=new_edge_id(),
                provenance=ledger_provenance,
                edge_type=EdgeType.OWED_TO,
                from_id=ledger_event_id,
                to_id=vendor_id,
            ),
        ]

        return GraphMappingResult(nodes=(ledger_event, commitment), edges=tuple(edges))


__all__ = ["UtilityBillExtractionStrategy"]
