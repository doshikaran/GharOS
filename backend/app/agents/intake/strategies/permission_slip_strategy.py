"""`ExtractionStrategy` for `document_type_ids.PERMISSION_SLIP`
(spec §5.4.2).

**Scope boundary:** spec's own note is that "signing authority matters"
for this type — the `owned_by` edge is capability-aware, meaning it must
point at a PERSON who actually `can_sign` (per `contracts.graph_types.
Person.can_sign`). This strategy has no `GraphReader` (ADR-008) and
therefore cannot check any household member's capability flags, so it
does not fabricate an `owned_by` edge to a guessed person — assigning a
capability-aware owner is left to a downstream agent with real graph
access (spec §7.3 Stage 4 "OWN"). Same reasoning for `depends_on` (needs
to know about existing prerequisite obligations already in the graph).
This strategy produces the OBLIGATION itself and its `states` edge only.
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

_TYPE_ID = type_id.PERMISSION_SLIP


class PermissionSlipExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        issuing_body_field = field_by_name(extracted_fields, "issuing_body")
        subject_field = field_by_name(extracted_fields, "subject_person")
        consent_field = field_by_name(extracted_fields, "consent_description")
        deadline_field = field_by_name(extracted_fields, "return_deadline")

        issuing_body = as_str(issuing_body_field.value) if issuing_body_field is not None else None
        subject_person = as_str(subject_field.value) if subject_field is not None else None
        consent_description = as_str(consent_field.value) if consent_field is not None else None
        return_deadline = parse_date_value(deadline_field.value) if deadline_field is not None else None

        missing = [
            n
            for n, v in (
                ("issuing_body", issuing_body),
                ("subject_person", subject_person),
                ("consent_description", consent_description),
                ("return_deadline", return_deadline),
            )
            if v is None
        ]
        if missing or consent_field is None:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert issuing_body is not None and subject_person is not None and consent_description is not None
        assert return_deadline is not None

        obligation_id = new_node_id("obligation")
        provenance = provenance_for(
            consent_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        obligation = Obligation(
            id=obligation_id,
            provenance=provenance,
            title=f"Sign & return: {consent_description} ({subject_person}, {issuing_body})",
            obligation_type="permission_slip",
            due_at=return_deadline,
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


__all__ = ["PermissionSlipExtractionStrategy"]
