"""`ExtractionStrategy` for `document_type_ids.MEDICAL_DOCUMENT`
(spec §5.4.2).

**Hard rule, carried forward verbatim from the registry entry (which
carries it from spec §5.4.2 itself):** extraction and scheduling only.
This strategy never interprets clinical meaning, never advises, and never
adjusts anything about a medication. Every `Constraint.original_text` here
is copied verbatim from `stated_restrictions` — `structured` is
deliberately left as an empty dict rather than populated with any
strategy-invented interpretation (e.g. guessing an allergen code from free
text) — a future agent with actual clinical-adjacent scope (not this one)
is the only place that judgment could ever legitimately happen, and spec
says it never does anywhere in this system.

Severity defaults to `SOFT` except when the restriction text itself
contains an explicit allergy marker ("allerg" as a substring, catching
"allergy"/"allergic"/"allergen") — even then, this is pattern-matching on
the literal words present, not an interpretation of clinical meaning.
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
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
)

from ....adapters import document_type_ids as type_id
from ._common import (
    as_str,
    field_by_name,
    new_edge_id,
    new_node_id,
    parse_date_value,
    provenance_for,
    slugify,
)
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.MEDICAL_DOCUMENT


class MedicalDocumentExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        patient_field = field_by_name(extracted_fields, "patient")
        provider_field = field_by_name(extracted_fields, "provider")

        patient = as_str(patient_field.value) if patient_field is not None else None
        provider = as_str(provider_field.value) if provider_field is not None else None
        if patient is None or provider is None or patient_field is None:
            missing = [n for n, v in (("patient", patient), ("provider", provider)) if v is None]
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))

        patient_pseudo_id = NodeId(f"person:{slugify(patient)}")
        nodes: list[object] = []
        edges: list[Edge] = []

        appointments_field = field_by_name(extracted_fields, "appointment_or_followup_dates")
        if appointments_field is not None and isinstance(appointments_field.value, list):
            appointment_provenance = provenance_for(
                appointments_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            )
            for raw_date in appointments_field.value:
                appointment_date = parse_date_value(raw_date)
                if appointment_date is None:
                    continue
                obligation_id = new_node_id("obligation")
                nodes.append(
                    Obligation(
                        id=obligation_id,
                        provenance=appointment_provenance,
                        title=f"Follow-up appointment: {provider} ({patient})",
                        obligation_type="medical_followup",
                        due_at=appointment_date,
                        must_start_by=None,
                        effort_estimate_minutes=None,
                        status=ObligationStatus.DERIVED,
                        stated_or_implied=ObligationDerivation.STATED,
                    )
                )
                edges.append(
                    Edge(
                        id=new_edge_id(),
                        provenance=appointment_provenance,
                        edge_type=EdgeType.STATES,
                        from_id=source_document_id,
                        to_id=obligation_id,
                    )
                )
                edges.append(
                    Edge(
                        id=new_edge_id(),
                        provenance=appointment_provenance,
                        edge_type=EdgeType.BENEFITS,
                        from_id=obligation_id,
                        to_id=patient_pseudo_id,
                    )
                )

        restrictions_field = field_by_name(extracted_fields, "stated_restrictions")
        if restrictions_field is not None and isinstance(restrictions_field.value, list):
            restriction_provenance = provenance_for(
                restrictions_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            )
            for raw_restriction in restrictions_field.value:
                if not isinstance(raw_restriction, str) or not raw_restriction:
                    continue
                is_allergy = "allerg" in raw_restriction.lower()
                severity = ConstraintSeverity.HARD if is_allergy else ConstraintSeverity.SOFT
                constraint_id = new_node_id("constraint")
                nodes.append(
                    Constraint(
                        id=constraint_id,
                        provenance=restriction_provenance,
                        kind=ConstraintKind.MEDICAL,
                        severity=severity,
                        validity_start=None,
                        validity_end=None,
                        structured={},
                        original_text=raw_restriction,
                    )
                )
                edges.append(
                    Edge(
                        id=new_edge_id(),
                        provenance=restriction_provenance,
                        edge_type=EdgeType.CONSTRAINS,
                        from_id=constraint_id,
                        to_id=patient_pseudo_id,
                    )
                )

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["MedicalDocumentExtractionStrategy"]
