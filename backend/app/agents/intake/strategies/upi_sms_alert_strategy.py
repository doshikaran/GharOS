"""`ExtractionStrategy` for `document_type_ids.UPI_SMS_ALERT`
(spec §5.4.2).

Produces one `LEDGER_EVENT` with `counterparty_raw` set to the *raw*
merchant/VPA string A3 extracted — never resolved against a VENDOR node
here. **No `owed_to` edge is produced** — this type's own
`target_edge_types` in `document_type_specs.py` is `(EdgeType.BELONGS_TO,)`
only (no `OWED_TO`), which already matches spec's own warning: "merchant
strings are notoriously opaque... low-confidence merchant resolution must
not drive a cancellation recommendation on its own." A low-confidence
merchant string stays exactly what it is — a raw string on the node, with
whatever confidence/derivation A3 assigned it — rather than being
promoted into a confident-looking edge to some vendor identity. `belongs_to`
(matching into an existing RECURRING_COMMITMENT / mandate series) needs
graph access this strategy does not have and is left to a downstream
reconciliation agent.
"""

from __future__ import annotations

from contracts.graph_types import (
    AgentId,
    ExtractedField,
    GraphMappingResult,
    LedgerEvent,
    LedgerEventKind,
    NodeId,
)

from ....adapters import document_type_ids as type_id
from ._common import as_float, as_str, field_by_name, new_node_id, parse_date_value, provenance_for
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.UPI_SMS_ALERT


class UpiSmsAlertExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        amount_field = field_by_name(extracted_fields, "amount")
        direction_field = field_by_name(extracted_fields, "direction")
        counterparty_field = field_by_name(extracted_fields, "counterparty_vpa_or_merchant")
        timestamp_field = field_by_name(extracted_fields, "timestamp")

        amount = as_float(amount_field.value) if amount_field is not None else None
        direction = as_str(direction_field.value) if direction_field is not None else None
        counterparty_raw = counterparty_field.value if counterparty_field is not None else None
        counterparty = as_str(counterparty_raw) or "(unresolved)"
        timestamp = parse_date_value(timestamp_field.value) if timestamp_field is not None else None

        missing = [
            n
            for n, v in (("amount", amount), ("direction", direction), ("timestamp", timestamp))
            if v is None
        ]
        if missing or amount_field is None:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert amount is not None and direction is not None and timestamp is not None

        kind = LedgerEventKind.CREDIT if direction.lower().startswith("credit") else LedgerEventKind.DEBIT
        provenance = provenance_for(
            amount_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        ledger_event = LedgerEvent(
            id=new_node_id("ledger_event"),
            provenance=provenance,
            kind=kind,
            amount=amount,
            currency="INR",
            occurred_at=timestamp,
            counterparty_raw=counterparty,
        )
        return GraphMappingResult(nodes=(ledger_event,), edges=())


__all__ = ["UpiSmsAlertExtractionStrategy"]
