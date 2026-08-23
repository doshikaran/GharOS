"""`ExtractionStrategy` for `document_type_ids.BANK_STATEMENT`
(spec §5.4.2 — "the reconciliation ground truth").

Produces one `LEDGER_EVENT` per transaction row in the extracted
`transactions` field. **Per-transaction provenance is coarser than the
receipt strategy's per-line items:** unlike `receipt`, this type has no
dedicated line-item sub-extractor (A3b is scoped to receipts/bills, spec
§15.2), so every transaction shares the single `transactions` field's own
confidence/region rather than each row carrying its own — a real,
documented limitation, not a silent one. A future dedicated statement
line-extractor could close this gap without changing this strategy's
shape (ADR-008's whole point).

`owed_to` uses the same deterministic pseudo-vendor-id pattern as
`receipt_strategy.py`; `belongs_to` (matching a transaction into an
existing RECURRING_COMMITMENT series) needs graph access this strategy
does not have and is left to a downstream reconciliation agent.
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

_TYPE_ID = type_id.BANK_STATEMENT


class BankStatementExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        transactions_field = field_by_name(extracted_fields, "transactions")
        if transactions_field is None or not isinstance(transactions_field.value, list):
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=("transactions",))

        provenance = provenance_for(
            transactions_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )

        nodes: list[object] = []
        edges: list[Edge] = []
        for raw_txn in transactions_field.value:
            if not isinstance(raw_txn, dict):
                continue
            description = as_str(raw_txn.get("description")) or "(unresolved transaction)"
            amount = as_float(raw_txn.get("amount"))
            occurred_at = parse_date_value(raw_txn.get("date"))
            direction = as_str(raw_txn.get("direction")) or "debit"
            if amount is None or occurred_at is None:
                continue

            kind = LedgerEventKind.CREDIT if direction.lower().startswith("credit") else LedgerEventKind.DEBIT
            event_id = new_node_id("ledger_event")
            nodes.append(
                LedgerEvent(
                    id=event_id,
                    provenance=provenance,
                    kind=kind,
                    amount=abs(amount),
                    currency="INR",
                    occurred_at=occurred_at,
                    counterparty_raw=description,
                )
            )
            edges.append(
                Edge(
                    id=new_edge_id(),
                    provenance=provenance,
                    edge_type=EdgeType.OWED_TO,
                    from_id=event_id,
                    to_id=NodeId(f"vendor:{slugify(description)}"),
                )
            )

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["BankStatementExtractionStrategy"]
