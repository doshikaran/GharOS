"""`ExtractionStrategy` for `document_type_ids.ATTENDANCE_REGISTER`
(spec §5.4.2 — "strictest confidence floors in the registry").

**No graph nodes/edges produced this phase, and this is deliberate, not
an oversight.** Spec's own line for this type is "attendance records on
STAFF PERSON node" — but `contracts.graph_types.Person` (frozen, CTO-
owned) has no attendance-marks field, and this type's own
`target_edge_types` in `document_type_specs.py` is empty (there is no
edge type for "feeds salary computation" — that is a downstream
deterministic solver input, spec §16.2, not a graph edge). Rather than
inventing an unauthorised shape to hold per-day marks, this strategy
returns an empty `GraphMappingResult` with the verbatim extracted
attendance data packaged into `verification_findings` as a human-readable
summary — durable, auditable text, ready for Phase 7's Staff Payroll
agent (A34) to consume once it exists, without this phase fabricating a
node shape ahead of the code that will actually need it.

**The safety-critical behaviour lives one layer up, in A3 itself**
(`document_extraction.py`): a below-floor handwritten mark is tagged
`Derivation.AMBIGUOUS` by A3's own code (comparing the model's reported
confidence against this type's `_ATTENDANCE_MIN_FLOOR`-gated schema,
`document_type_specs.py`), never silently accepted as a confident
presence/absence mark — this strategy's job is only to summarise what A3
already tagged, never to re-decide it.
"""

from __future__ import annotations

from contracts.graph_types import AgentId, Derivation, ExtractedField, GraphMappingResult, NodeId

from ._common import as_str, field_by_name


class AttendanceRegisterExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        staff_field = field_by_name(extracted_fields, "staff_member")
        month_field = field_by_name(extracted_fields, "month")
        marks_field = field_by_name(extracted_fields, "per_day_presence_marks")

        staff_member = as_str(staff_field.value) if staff_field is not None else "(unresolved staff member)"
        month = as_str(month_field.value) if month_field is not None else "(unresolved month)"

        findings: list[str] = [f"attendance register: {staff_member}, {month}"]
        ambiguous_fields = [
            field.name for field in extracted_fields if field.derivation is Derivation.AMBIGUOUS
        ]
        if ambiguous_fields:
            findings.append(
                "below-floor (ambiguous) fields, surfaced for human review, never inferred: "
                + ", ".join(ambiguous_fields)
            )
        if marks_field is not None:
            findings.append(
                f"per_day_presence_marks confidence={marks_field.confidence:.2f} "
                f"derivation={marks_field.derivation.value} region={marks_field.source_region}"
            )
        else:
            findings.append("per_day_presence_marks: not extracted — full image requires human review")

        return GraphMappingResult(nodes=(), edges=(), verification_findings=tuple(findings))


__all__ = ["AttendanceRegisterExtractionStrategy"]
