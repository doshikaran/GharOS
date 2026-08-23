"""`ExtractionStrategy` for `document_type_ids.GOVERNMENT_NOTICE`
(spec §5.4.2 — "typically R2+ given consequence").

Produces one high-consequence, deadline-critical OBLIGATION with a
`states` edge. Risk-tier classification itself (R2+) is Phase 5's
Confidence Arbiter's job, not this strategy's — this module only records
`penalty_for_noncompliance` verbatim on the obligation's own metadata-free
title/type so a downstream arbiter has the literal text to reason from,
never a strategy-invented urgency score.
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

_TYPE_ID = type_id.GOVERNMENT_NOTICE


class GovernmentNoticeExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        issuing_body_field = field_by_name(extracted_fields, "issuing_body")
        required_action_field = field_by_name(extracted_fields, "required_action")
        deadline_field = field_by_name(extracted_fields, "deadline")

        issuing_body = as_str(issuing_body_field.value) if issuing_body_field is not None else None
        required_action = as_str(required_action_field.value) if required_action_field is not None else None
        deadline = parse_date_value(deadline_field.value) if deadline_field is not None else None

        missing = [
            n
            for n, v in (
                ("issuing_body", issuing_body),
                ("required_action", required_action),
                ("deadline", deadline),
            )
            if v is None
        ]
        if missing or required_action_field is None:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert issuing_body is not None and required_action is not None and deadline is not None

        provenance = provenance_for(
            required_action_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        obligation_id = new_node_id("obligation")
        obligation = Obligation(
            id=obligation_id,
            provenance=provenance,
            title=f"{required_action} ({issuing_body})",
            obligation_type="government_notice_compliance",
            due_at=deadline,
            must_start_by=None,
            effort_estimate_minutes=None,
            status=ObligationStatus.DERIVED,
            stated_or_implied=ObligationDerivation.STATED,
        )
        edge = Edge(
            id=new_edge_id(),
            provenance=provenance,
            edge_type=EdgeType.STATES,
            from_id=source_document_id,
            to_id=obligation_id,
        )
        return GraphMappingResult(nodes=(obligation,), edges=(edge,))


__all__ = ["GovernmentNoticeExtractionStrategy"]
