"""`ExtractionStrategy` for `document_type_ids.INSURANCE_DOCUMENT`
(spec §5.4.2).

Produces a `RECURRING_COMMITMENT` (the policy itself), an OBLIGATION for
the renewal deadline (with a `states` edge — this type's `target_node_types`
does include `OBLIGATION`, unlike `utility_bill`'s registry entry), and a
CONSTRAINT when `coverage_limits` was extracted (feeds Council Finance
reasoning per spec's own note).

**Same class of registry inconsistency as `utility_bill_strategy.py`,
flagged the same way:** this entry's `target_edge_types` includes
`EdgeType.BELONGS_TO` (spec's edge table: `LEDGER_EVENT -> RECURRING_
COMMITMENT`), but `target_node_types` has no `LEDGER_EVENT` — there is
nothing to originate that edge from at this stage (a premium payment is a
future Ledger-ingestion event, not part of the policy document itself).
No `belongs_to` edge is produced here; see this phase's final report.
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
    RecurringCommitment,
)

from ....adapters import document_type_ids as type_id
from ._common import (
    as_float,
    as_str,
    cadence_from_period,
    field_by_name,
    new_edge_id,
    new_node_id,
    parse_date_value,
    provenance_for,
)
from .errors import MappingInputIncomplete

_TYPE_ID = type_id.INSURANCE_DOCUMENT


class InsuranceDocumentExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        insurer_field = field_by_name(extracted_fields, "insurer")
        premium_field = field_by_name(extracted_fields, "premium")
        coverage_type_field = field_by_name(extracted_fields, "coverage_type")
        renewal_field = field_by_name(extracted_fields, "renewal_date")
        due_date_field = field_by_name(extracted_fields, "premium_due_date")

        insurer = as_str(insurer_field.value) if insurer_field is not None else None
        premium = as_float(premium_field.value) if premium_field is not None else None
        coverage_type = as_str(coverage_type_field.value) if coverage_type_field is not None else None
        renewal_date = parse_date_value(renewal_field.value) if renewal_field is not None else None

        missing = [
            n
            for n, v in (
                ("insurer", insurer),
                ("premium", premium),
                ("coverage_type", coverage_type),
                ("renewal_date", renewal_date),
            )
            if v is None
        ]
        if missing or premium_field is None or renewal_field is None:
            raise MappingInputIncomplete(type_id=_TYPE_ID, missing_fields=tuple(missing))
        assert insurer is not None and premium is not None and coverage_type is not None
        assert renewal_date is not None

        commitment_provenance = provenance_for(
            premium_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        cadence = cadence_from_period(
            due_date_field.value if due_date_field is not None else None, renewal_field.value
        )
        commitment = RecurringCommitment(
            id=new_node_id("recurring_commitment"),
            provenance=commitment_provenance,
            label=f"{insurer} {coverage_type} policy",
            counterparty=insurer,
            amount=premium,
            cadence=cadence,
            price_history=((renewal_date, premium),),
            last_used_at=None,
            status="active",
        )

        renewal_provenance = provenance_for(
            renewal_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        renewal_obligation_id = new_node_id("obligation")
        renewal_obligation = Obligation(
            id=renewal_obligation_id,
            provenance=renewal_provenance,
            title=f"Renew {coverage_type} policy — {insurer}",
            obligation_type="insurance_renewal",
            due_at=renewal_date,
            must_start_by=None,
            effort_estimate_minutes=None,
            status=ObligationStatus.DERIVED,
            stated_or_implied=ObligationDerivation.STATED,
        )

        nodes: list[object] = [commitment, renewal_obligation]
        edges: list[Edge] = [
            Edge(
                id=new_edge_id(),
                provenance=renewal_provenance,
                edge_type=EdgeType.STATES,
                from_id=source_document_id,
                to_id=renewal_obligation_id,
            )
        ]

        coverage_limits_field = field_by_name(extracted_fields, "coverage_limits")
        coverage_limits = as_float(coverage_limits_field.value) if coverage_limits_field is not None else None
        if coverage_limits is not None and coverage_limits_field is not None:
            constraint_provenance = provenance_for(
                coverage_limits_field, source_document_id=source_document_id, deriving_agent=deriving_agent
            )
            nodes.append(
                Constraint(
                    id=new_node_id("constraint"),
                    provenance=constraint_provenance,
                    kind=ConstraintKind.FINANCIAL,
                    severity=ConstraintSeverity.SOFT,
                    validity_start=None,
                    validity_end=renewal_date,
                    structured={"coverage_limit": str(coverage_limits), "coverage_type": coverage_type},
                    original_text=f"{coverage_type} coverage limit: {coverage_limits}",
                )
            )

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["InsuranceDocumentExtractionStrategy"]
