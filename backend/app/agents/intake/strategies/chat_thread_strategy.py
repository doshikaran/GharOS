"""`ExtractionStrategy` for `document_type_ids.CHAT_THREAD` (spec §5.4.2 —
"the most polymorphic input").

Produces one OBLIGATION per literally-stated `embedded_commitments` entry
("I'll pick her up Friday" is a real household obligation the moment it
is said, spec §5.4.2's own example) with a `states` edge. `due_at` is left
`None` — resolving "Friday" into an actual date from conversational
context is reasoning (A12 Implication Agent, Phase 4), not literal
extraction; this strategy records exactly the stated commitment text and
nothing more.

Complaints, leave notifications, and intentions are not turned into graph
nodes by this strategy — spec's own Nodes: line for this type names only
OBLIGATION as an actual node type (see `document_type_specs.py`'s
`_chat_thread_spec` docstring: "valuation signals," "staff leave records"
etc. describe what a message *can evidence* downstream, not a distinct
graph node type this entry could name) — they remain queryable on the
SOURCE_DOCUMENT's own extracted fields for whichever future subsystem
(Fair Allocator, Household Ledger) consumes them.
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

from ._common import field_by_name, new_edge_id, new_node_id, provenance_for


class ChatThreadExtractionStrategy:
    """Structurally satisfies `contracts.graph_types.ExtractionStrategy`."""

    def map_to_graph(
        self,
        *,
        source_document_id: NodeId,
        extracted_fields: tuple[ExtractedField, ...],
        deriving_agent: AgentId,
    ) -> GraphMappingResult:
        commitments_field = field_by_name(extracted_fields, "embedded_commitments")
        if commitments_field is None or not isinstance(commitments_field.value, list):
            return GraphMappingResult(nodes=(), edges=())

        provenance = provenance_for(
            commitments_field, source_document_id=source_document_id, deriving_agent=deriving_agent
        )
        nodes: list[object] = []
        edges: list[Edge] = []
        for raw_commitment in commitments_field.value:
            if not isinstance(raw_commitment, str) or not raw_commitment:
                continue
            obligation_id = new_node_id("obligation")
            nodes.append(
                Obligation(
                    id=obligation_id,
                    provenance=provenance,
                    title=raw_commitment,
                    obligation_type="chat_commitment",
                    due_at=None,
                    must_start_by=None,
                    effort_estimate_minutes=None,
                    status=ObligationStatus.DERIVED,
                    stated_or_implied=ObligationDerivation.STATED,
                )
            )
            edges.append(
                Edge(
                    id=new_edge_id(),
                    provenance=provenance,
                    edge_type=EdgeType.STATES,
                    from_id=source_document_id,
                    to_id=obligation_id,
                )
            )

        return GraphMappingResult(nodes=tuple(nodes), edges=tuple(edges))


__all__ = ["ChatThreadExtractionStrategy"]
