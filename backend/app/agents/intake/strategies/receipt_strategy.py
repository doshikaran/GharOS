"""`ExtractionStrategy` for `document_type_ids.RECEIPT` (spec §5.4.2).

Produces one `LEDGER_EVENT` and one `PURCHASE_ITEM` per line item, with
`line_item_of` (item -> event) and `owed_to` (event -> merchant) edges.

**Scope boundary, deliberate (ADR-008):** `map_to_graph` receives only
`extracted_fields` — no `GraphReader`. The receipt's `verifies` /
`contradicts` / `discharges` / `substitutes` / `evidences_effort` edges
all require comparing against *existing* graph state (an open shopping
OBLIGATION, an active CONSTRAINT, a prior purchase) that this method
structurally cannot see. Those are `A3c` Verification Agent's job
(`verification_agent.py`), which does hold a `GraphReader`. This
strategy produces only the edges knowable from the document alone.

**Line items input contract:** this strategy expects an `ExtractedField`
named `"line_items"` whose `.value` is a `tuple[LineItemExtraction, ...]`
— A3b's own typed output (`line_item_extraction.build_line_items_field`
packages a `LineItemExtractionResult` into exactly this shape). A3's own
generic `"line_items"` JSON field (if present, from the shared field
schema) is not used here — A3b's dedicated per-line confidence/region/
category-normalisation is strictly richer, and mixing the two would
silently prefer whichever happened to be present.
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
    Provenance,
    PurchaseItem,
    SourceRef,
)

from ....adapters import document_type_ids as type_id
from ..line_item_extraction import LineItemExtraction
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

_TYPE_ID = type_id.RECEIPT


class ReceiptExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        merchant_field = field_by_name(extracted_fields, "merchant_name")
        total_field = field_by_name(extracted_fields, "total")
        datetime_field = field_by_name(extracted_fields, "transaction_datetime")

        merchant_name = as_str(merchant_field.value) if merchant_field is not None else None
        total_amount = as_float(total_field.value) if total_field is not None else None
        occurred_at = parse_date_value(datetime_field.value) if datetime_field is not None else None

        missing = [
            field_name
            for field_name, value in (
                ("merchant_name", merchant_name),
                ("total", total_amount),
                ("transaction_datetime", occurred_at),
            )
            if value is None
        ]
        if missing:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert merchant_field is not None and total_field is not None  # narrowed by the check above
        assert merchant_name is not None and total_amount is not None and occurred_at is not None

        ledger_event_id = new_node_id("ledger_event")
        ledger_event_provenance = provenance_for(
            total_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        ledger_event = LedgerEvent(
            id=ledger_event_id,
            provenance=ledger_event_provenance,
            kind=LedgerEventKind.DEBIT,
            amount=total_amount,
            currency="INR",
            occurred_at=occurred_at,
            counterparty_raw=merchant_name,
        )

        # Deterministic pseudo-id, not a written VENDOR node — see module
        # docstring. A5 Entity Resolution (or a future dedicated vendor
        # resolver) is responsible for reconciling this against a real
        # VENDOR node; this strategy does not create one (spec §5.4.2's
        # RECEIPT `Nodes:` line names only LEDGER_EVENT and PURCHASE_ITEM).
        vendor_id = NodeId(f"vendor:{slugify(merchant_name)}")

        nodes: list[object] = [ledger_event]
        edges: list[Edge] = [
            Edge(
                id=new_edge_id(),
                provenance=ledger_event_provenance,
                edge_type=EdgeType.OWED_TO,
                from_id=ledger_event_id,
                to_id=vendor_id,
            )
        ]

        line_items_field = field_by_name(extracted_fields, "line_items")
        line_items: tuple[LineItemExtraction, ...] = ()
        if line_items_field is not None and isinstance(line_items_field.value, tuple):
            line_items = tuple(
                item for item in line_items_field.value if isinstance(item, LineItemExtraction)
            )

        for line_item in line_items:
            item_id = new_node_id("purchase_item")
            item_provenance = Provenance(
                derivation=line_item.derivation,
                source_ref=SourceRef(source_document_id=source_document_id, region=line_item.source_region),
                confidence=line_item.confidence,
                deriving_agent=AgentId("A3b"),
                created_at=ledger_event_provenance.created_at,
            )
            purchase_item = PurchaseItem(
                id=item_id,
                provenance=item_provenance,
                ledger_event_id=ledger_event_id,
                description=line_item.description,
                normalized_category=line_item.normalized_category,
                quantity=line_item.quantity,
                unit_price=line_item.unit_price,
                line_total=line_item.line_total,
            )
            nodes.append(purchase_item)
            edges.append(
                Edge(
                    id=new_edge_id(),
                    provenance=item_provenance,
                    edge_type=EdgeType.LINE_ITEM_OF,
                    from_id=item_id,
                    to_id=ledger_event_id,
                )
            )

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["ReceiptExtractionStrategy"]
