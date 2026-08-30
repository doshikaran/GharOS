"""`ExtractionStrategy` for `document_type_ids.ATTENDANCE_REGISTER`
(spec §5.4.2 — "strictest confidence floors in the registry").

**Writes real graph content (ADR-013, DEBT-004's repayment).** ADR-013
(Phase 7) added the `AttendanceRecord` node type and `EdgeType.ATTENDANCE_OF`,
and `document_type_specs.py`'s `ATTENDANCE_REGISTER` entry declares
`ATTENDANCE_RECORD` / `attendance_of` as targets. This strategy produces,
for a confidently-extracted register:

- one `AttendanceRecord` — the staff member's marks for one calendar
  month, per-day marks transcribed into `daily_marks` and tallied into the
  `days_present` / `days_absent` / `days_on_leave` / `total_days_in_period`
  rollup, `advance_notations` carried as raw cross-reference text only
  (never authoritative — real advances are `LedgerEvent` nodes, ADR-013);
- the salary-payment `Obligation` the register feeds (spec §5.4.2 "feeds
  salary computation" / §10.3), `stated_or_implied=IMPLIED`,
  `status=DERIVED`;
- the `implies` edge SOURCE_DOCUMENT -> that salary `Obligation` — there is
  no `EdgeType` connecting SOURCE_DOCUMENT to ATTENDANCE_RECORD directly
  (ADR-013), so the obligation carries the document anchor.

**Safety (spec §5.4.2: "handwriting misread directly causes wrong salary
payment ... below threshold, present the image to the human, never
infer").** When A3 tags `per_day_presence_marks` `Derivation.AMBIGUOUS`
(any day's mark below this type's 0.95 floor), this strategy writes NO
graph nodes: it surfaces the register for human review through
`verification_findings` and stops. A wrong `AttendanceRecord` feeds a
wrong salary, so an uncertain register never becomes one. A3 owns the
AMBIGUOUS tagging (`document_extraction.py`); this strategy only respects
it, never re-decides it.

**Entity resolution (ADR-008).** `map_to_graph` has no `GraphReader`, so
it cannot resolve the extracted staff name to a PERSON node id on its
own — the same limitation, and the same precedent, as
`PermissionSlipExtractionStrategy`'s capability-aware `owned_by`: it does
not fabricate an owner. An optional `staff_index` (name -> PERSON
`NodeId`) may be supplied at construction (the registry constructs this
strategy with none). With a hit, the `attendance_of` edge is emitted here;
without one, `staff_person_id` is left as the explicit `person:unresolved`
sentinel, no `attendance_of` edge is produced, and a
`verification_findings` note records that a downstream entity-resolution
pass must add the edge.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from contracts.graph_types import (
    AgentId,
    AttendanceRecord,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    ExtractedField,
    GraphMappingResult,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Provenance,
    SourceRef,
)

from ....adapters import document_type_ids as type_id
from ._common import as_str, field_by_name, provenance_for
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.ATTENDANCE_REGISTER
_UNRESOLVED_STAFF_ID = NodeId("person:unresolved")
"""`AttendanceRecord.staff_person_id` when the strategy has no way to
resolve the extracted name — an explicit sentinel a downstream
entity-resolution pass keys on, never a guessed PERSON id."""

_PRESENT = "present"
_ABSENT = "absent"
_ON_LEAVE = "leave"


def _tally_daily_marks(raw: object) -> dict[str, str]:
    """A3's `per_day_presence_marks` (a list of `{"day", "mark"}` dicts)
    into a `day-of-month -> mark` dict — a deterministic transcription of
    literal extracted data, never a guess. An unrecognised mark string is
    kept verbatim (ADR-013 permits `"unknown"`), so a day this strategy
    does not classify into the rollup is still auditable against the
    original register rather than dropped."""
    marks: dict[str, str] = {}
    if not isinstance(raw, list):
        return marks
    for entry in raw:
        if isinstance(entry, dict) and "day" in entry and "mark" in entry:
            marks[str(entry["day"])] = str(entry["mark"])
    return marks


class AttendanceRegisterExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def __init__(self, staff_index: Mapping[str, NodeId] | None = None) -> None:
        # name -> PERSON NodeId. Empty by default — the registry
        # (`register_all_strategies`) constructs this strategy with no
        # arguments. An ingestion caller holding an already-resolved staff
        # roster may inject one so the `attendance_of` edge is written here
        # rather than deferred to a downstream entity-resolution pass.
        self._staff_index: dict[str, NodeId] = dict(staff_index or {})

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
        advance_field = field_by_name(extracted_fields, "advance_notations_margin")

        staff_name = as_str(staff_field.value) if staff_field is not None else None
        month = as_str(month_field.value) if month_field is not None else None

        missing = tuple(
            name
            for name, present in (
                ("staff_member", staff_name is not None),
                ("month", month is not None),
                ("per_day_presence_marks", marks_field is not None),
            )
            if not present
        )
        if missing:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=missing)
        assert staff_field is not None and staff_name is not None
        assert month_field is not None and month is not None
        assert marks_field is not None

        register_summary = f"attendance register: {staff_name}, {month}"

        # Safety gate (spec §5.4.2): an uncertain register never becomes an
        # AttendanceRecord — that would feed a wrong salary. Surface it for
        # human review, write nothing.
        if marks_field.derivation is Derivation.AMBIGUOUS:
            ambiguous_fields = tuple(
                field.name for field in extracted_fields if field.derivation is Derivation.AMBIGUOUS
            )
            return GraphMappingResult(
                nodes=(),
                edges=(),
                verification_findings=(
                    register_summary,
                    "below-floor (ambiguous) fields, surfaced for human review, never inferred: "
                    + ", ".join(ambiguous_fields or ("per_day_presence_marks",)),
                    "no AttendanceRecord written — an uncertain register must not feed salary computation",
                ),
            )

        daily_marks = _tally_daily_marks(marks_field.value)
        raw_advances = advance_field.value if advance_field is not None else None
        advance_notations = (
            tuple(str(item) for item in raw_advances) if isinstance(raw_advances, list) else ()
        )

        record = AttendanceRecord(
            id=NodeId(f"attendance:{source_document_id}"),
            provenance=provenance_for(
                marks_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            ),
            staff_person_id=self._staff_index.get(staff_name, _UNRESOLVED_STAFF_ID),
            month=month,
            days_present=sum(1 for mark in daily_marks.values() if mark == _PRESENT),
            days_absent=sum(1 for mark in daily_marks.values() if mark == _ABSENT),
            days_on_leave=sum(1 for mark in daily_marks.values() if mark == _ON_LEAVE),
            total_days_in_period=len(daily_marks),
            daily_marks=daily_marks,
            advance_notations=advance_notations,
        )

        # The salary-payment obligation the register feeds (spec §5.4.2 /
        # §10.3). Its provenance also anchors the `implies` edge, since no
        # EdgeType connects SOURCE_DOCUMENT to ATTENDANCE_RECORD (ADR-013).
        salary_provenance = Provenance(
            derivation=Derivation.INFERRED,
            source_ref=SourceRef(source_document_id=source_document_id, region=marks_field.source_region),
            confidence=min(staff_field.confidence, month_field.confidence),
            deriving_agent=deriving_agent,
            created_at=datetime.now(UTC),
        )
        salary_obligation = Obligation(
            id=NodeId(f"obligation:salary:{source_document_id}"),
            provenance=salary_provenance,
            title=f"Pay {staff_name}'s salary for {month}",
            obligation_type="payment",
            due_at=None,
            must_start_by=None,
            effort_estimate_minutes=5,
            status=ObligationStatus.DERIVED,
            stated_or_implied=ObligationDerivation.IMPLIED,
        )
        implies_edge = Edge(
            id=EdgeId(f"edge:implies:{salary_obligation.id}"),
            provenance=salary_provenance,
            edge_type=EdgeType.IMPLIES,
            from_id=source_document_id,
            to_id=salary_obligation.id,
        )

        nodes: tuple[object, ...] = (record, salary_obligation)
        findings: list[str] = [register_summary]

        resolved_staff = self._staff_index.get(staff_name)
        if resolved_staff is None:
            findings.append(
                f"staff_member {staff_name!r} not resolved to a PERSON node; attendance_of edge "
                "left for a downstream entity-resolution pass"
            )
            return GraphMappingResult(
                nodes=nodes, edges=(implies_edge,), verification_findings=tuple(findings)
            )

        attendance_of_edge = Edge(
            id=EdgeId(f"edge:attendance_of:{record.id}"),
            provenance=provenance_for(
                staff_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            ),
            edge_type=EdgeType.ATTENDANCE_OF,
            from_id=record.id,
            to_id=resolved_staff,
        )
        return GraphMappingResult(
            nodes=nodes,
            edges=(attendance_of_edge, implies_edge),
            verification_findings=tuple(findings),
        )


__all__ = ["AttendanceRegisterExtractionStrategy"]
