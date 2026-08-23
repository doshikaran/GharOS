"""`ExtractionStrategy` for `document_type_ids.QUOTE_ESTIMATE`
(spec §5.4.2).

Always produces a `PROVIDER` node from the quote. **No `BRANCH`/
`grounded_in` edge this phase** — spec's own Nodes: line makes `BRANCH`
conditional ("if part of an active Decision"), and this strategy has no
way to know whether an active DECISION exists (no `GraphReader`, ADR-008)
or which one this quote would attach to. A future Household Simulator/
Decision-aware caller (Phase 11) is responsible for wiring a quote into an
active Decision's branch set — this strategy only produces the durable
PROVIDER record every quote should leave behind regardless.
"""

from __future__ import annotations

from contracts.graph_types import AgentId, ExtractedField, GraphMappingResult, NodeId, Provider

from ....adapters import document_type_ids as type_id
from ._common import as_str, field_by_name, new_node_id, provenance_for
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.QUOTE_ESTIMATE


def _total_from_line_items(value: object) -> float | None:
    if not isinstance(value, list):
        return None
    total = 0.0
    found_any = False
    for raw_line in value:
        if isinstance(raw_line, dict):
            amount = raw_line.get("amount") or raw_line.get("cost") or raw_line.get("line_total")
            if isinstance(amount, int | float) and not isinstance(amount, bool):
                total += float(amount)
                found_any = True
    return total if found_any else None


class QuoteEstimateExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        provider_field = field_by_name(extracted_fields, "provider")
        scope_field = field_by_name(extracted_fields, "scope_of_work")

        provider_name = as_str(provider_field.value) if provider_field is not None else None
        scope_of_work = as_str(scope_field.value) if scope_field is not None else None
        if provider_name is None or scope_of_work is None or provider_field is None:
            missing = [
                n for n, v in (("provider", provider_name), ("scope_of_work", scope_of_work)) if v is None
            ]
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))

        line_items_field = field_by_name(extracted_fields, "line_item_costs")
        estimated_total = (
            _total_from_line_items(line_items_field.value) if line_items_field is not None else None
        )

        provenance = provenance_for(
            provider_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        provider = Provider(
            id=new_node_id("provider"),
            provenance=provenance,
            name=provider_name,
            category="quote_respondent",
            rating=None,
            distance_km=None,
            availability_notes=None,
            price_band=f"~{estimated_total:.2f}" if estimated_total is not None else None,
            specialisations=(scope_of_work,),
        )
        return GraphMappingResult(nodes=(provider,), edges=())


__all__ = ["QuoteEstimateExtractionStrategy"]
