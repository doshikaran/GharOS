"""`ExtractionStrategy` for `document_type_ids.WARRANTY` (spec §5.4.2,
ADR-009).

Produces a claim-or-lose OBLIGATION (due at `warranty_expiry`) with a
`states` edge, and — when the caller supplies a link back to the
originating receipt — a `covers` edge (`EdgeType.COVERS`, ADR-009) from
that OBLIGATION to the specific `PURCHASE_ITEM` this warranty protects.
This is "why receipt line-item extraction matters months later" (spec
§5.4.2) made real: a warranty claim obligation that a household member
opens two years later still points at the exact original purchase line.

**How the link is supplied, and why (ADR-008 scope note):**
`ExtractionStrategy.map_to_graph`'s signature (frozen, `contracts/`) takes
only `extracted_fields` — no `GraphReader`, so this strategy cannot itself
search the graph for "the receipt this warranty belongs to" (a genuine
cross-document matching problem — same product, plausible purchase date,
but no shared identifier printed on either document). The pipeline may
supply the answer as a synthetic `ExtractedField` named
`"originating_purchase_item_id"` (value = the `PurchaseItem.id` string) —
appended to `extracted_fields` by whatever resolved the link (a human
confirming "this warranty is for the fridge from last month's receipt,"
or a future cross-document linking agent) before calling this strategy.
When present, the `covers` edge is produced with that field's own
provenance carried forward, so it stays honestly attributable to whatever
did the linking. When absent, no `covers` edge is produced and a
`verification_finding` says so explicitly — never a guessed link.
"""

from __future__ import annotations

from contracts.graph_types import (
    AgentId,
    Edge,
    EdgeType,
    ExtractedField,
    GraphMappingResult,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
)

from ....adapters import document_type_ids as type_id
from ._common import as_str, field_by_name, new_edge_id, new_node_id, parse_date_value, provenance_for
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.WARRANTY


class WarrantyExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        product_field = field_by_name(extracted_fields, "product")
        expiry_field = field_by_name(extracted_fields, "warranty_expiry")

        product = as_str(product_field.value) if product_field is not None else None
        warranty_expiry = parse_date_value(expiry_field.value) if expiry_field is not None else None
        missing = [n for n, v in (("product", product), ("warranty_expiry", warranty_expiry)) if v is None]
        if missing or expiry_field is None:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert product is not None and warranty_expiry is not None

        provenance = provenance_for(
            expiry_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        obligation_id = new_node_id("obligation")
        obligation = Obligation(
            id=obligation_id,
            provenance=provenance,
            title=f"Claim or lose warranty: {product}",
            obligation_type="warranty_claim_or_lose",
            due_at=warranty_expiry,
            must_start_by=None,
            effort_estimate_minutes=None,
            status=ObligationStatus.DERIVED,
            stated_or_implied=ObligationDerivation.STATED,
        )
        edges: list[Edge] = [
            Edge(
                id=new_edge_id(),
                provenance=provenance,
                edge_type=EdgeType.STATES,
                from_id=source_document_id,
                to_id=obligation_id,
            )
        ]
        findings: list[str] = []

        link_field = field_by_name(extracted_fields, "originating_purchase_item_id")
        if link_field is not None and isinstance(link_field.value, str) and link_field.value:
            link_provenance = provenance_for(
                link_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            )
            edges.append(
                Edge(
                    id=new_edge_id(),
                    provenance=link_provenance,
                    edge_type=EdgeType.COVERS,
                    from_id=obligation_id,
                    to_id=NodeId(link_field.value),
                )
            )
        else:
            findings.append(
                f"warranty for '{product}' has no originating_purchase_item_id link supplied — "
                "'covers' edge not produced; link required before this warranty can be traced back "
                "to its receipt line item."
            )

        return GraphMappingResult(
            nodes=(obligation,), edges=tuple(edges), verification_findings=tuple(findings)
        )


__all__ = ["WarrantyExtractionStrategy"]
