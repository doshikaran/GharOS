"""`ExtractionStrategy` for `document_type_ids.SCHOOL_COMMUNICATION`
(spec §5.4.2 — "the implication-rich case").

**This phase produces the STATED side only.** Spec's own edge list for
this type is `states`/`implies`/`benefits`/`violates` — but deriving an
*implied* obligation (the flagship worked example, spec §7.3: a Wednesday
slip deadline implying a Monday must-sign-by) is A12 Implication Agent's
job (Phase 4), and detecting a `violates` collision against an existing
CONSTRAINT requires graph access this strategy does not have (ADR-008).
This strategy produces one OBLIGATION per literally-stated requirement
(plus the top-level communication itself) with `states` edges only —
exactly what is printed, nothing implied.

`benefits` (OBLIGATION -> the student) uses the same deterministic
pseudo-id pattern as the receipt strategy's `owed_to` (a `person:<slug>`
id, not a resolved PERSON node) — A5 Entity Resolution is responsible for
reconciling it against a real PERSON.
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

_TYPE_ID = type_id.SCHOOL_COMMUNICATION


class SchoolCommunicationExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        institution_field = field_by_name(extracted_fields, "institution")
        student_field = field_by_name(extracted_fields, "student")
        comm_type_field = field_by_name(extracted_fields, "communication_type")

        institution = as_str(institution_field.value) if institution_field is not None else None
        student = as_str(student_field.value) if student_field is not None else None
        communication_type = as_str(comm_type_field.value) if comm_type_field is not None else None
        missing = [
            n
            for n, v in (
                ("institution", institution),
                ("student", student),
                ("communication_type", communication_type),
            )
            if v is None
        ]
        if missing or comm_type_field is None:
            raise MappingInputIncomplete(
                type_id=_TYPE_ID, missing_fields=tuple(missing) or ("communication_type",)
            )
        assert institution is not None and student is not None and communication_type is not None

        deadline_field = field_by_name(extracted_fields, "response_deadline")
        event_date_field = field_by_name(extracted_fields, "event_date")
        due_at = (
            parse_date_value(deadline_field.value)
            if deadline_field is not None
            else (parse_date_value(event_date_field.value) if event_date_field is not None else None)
        )
        student_pseudo_id = NodeId(f"person:{slugify(student)}")

        def _make_obligation(
            *, title: str, source_field: ExtractedField
        ) -> tuple[Obligation, tuple[Edge, ...]]:
            obligation_id = new_node_id("obligation")
            provenance = provenance_for(
                source_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            )
            obligation = Obligation(
                id=obligation_id,
                provenance=provenance,
                title=title,
                obligation_type="school_communication_response",
                due_at=due_at,
                must_start_by=None,
                effort_estimate_minutes=None,
                status=ObligationStatus.DERIVED,
                stated_or_implied=ObligationDerivation.STATED,
            )
            edges = (
                Edge(
                    id=new_edge_id(),
                    provenance=provenance,
                    edge_type=EdgeType.STATES,
                    from_id=source_document_id,
                    to_id=obligation_id,
                ),
                Edge(
                    id=new_edge_id(),
                    provenance=provenance,
                    edge_type=EdgeType.BENEFITS,
                    from_id=obligation_id,
                    to_id=student_pseudo_id,
                ),
            )
            return obligation, edges

        nodes: list[object] = []
        edges: list[Edge] = []

        primary, primary_edges = _make_obligation(
            title=f"{communication_type} — {institution} ({student})", source_field=comm_type_field
        )
        nodes.append(primary)
        edges.extend(primary_edges)

        requirements_field = field_by_name(extracted_fields, "requirements")
        if requirements_field is not None and isinstance(requirements_field.value, list):
            for raw_requirement in requirements_field.value:
                if not isinstance(raw_requirement, str) or not raw_requirement:
                    continue
                requirement_obligation, requirement_edges = _make_obligation(
                    title=f"Provide: {raw_requirement} ({student}, {institution})",
                    source_field=requirements_field,
                )
                nodes.append(requirement_obligation)
                edges.extend(requirement_edges)

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["SchoolCommunicationExtractionStrategy"]
