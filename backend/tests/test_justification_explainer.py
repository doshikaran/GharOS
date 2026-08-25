"""`JustificationExplainer` proven against the real seeded demo household
(`seeds.demo_household`) — a genuine multi-hop chain, not a 2-node happy
path (mirrors `test_traversals.py`'s own standard, per the E1 charter and
this phase's own test requirement).

The chain exercised here, starting from `obligation-renew-prescription`
(O2, "Renew Dadi's blood-pressure prescription"):

    O2 --IMPLIES(rev)--> doc-pharmacy-sms (depth 1, region "msg-1")
    O2 --COMPLETES_INTO--> outcome-prescription-delivered (depth 1)
    O2 <--DEPENDS_ON-- obligation-visit-pharmacy (O4) (depth 1)
    ... continuing through council positions, branches, a decision, a
    conflicting obligation, and a constraint, out to three distinct
    SOURCE_DOCUMENT roots: doc-pharmacy-sms, doc-freshmart-receipt (no
    resolvable region — the seed data's GROUNDED_IN wiring for this edge
    doesn't point back to the branch's own source), and doc-school-whatsapp
    (region "msg-9").

This is deliberately computed from the real seed graph rather than
hand-asserted step-by-step for every hop — the test instead pins the
externally-meaningful contract: root id, that real multi-hop depth is
reached, that all three real SOURCE_DOCUMENT roots are found with the
right regions, and that every `via_edge` is a real justificatory edge type.
"""

from __future__ import annotations

import pytest
from contracts.graph_types import EdgeType, NodeId

from app.graph.errors import NodeNotFound
from app.graph.justification import JUSTIFICATORY_EDGE_TYPES, JustificationExplainer
from app.persistence.firestore_store import FirestoreGraphStore
from seeds.demo_household import SeedResult

O2_PRESCRIPTION = NodeId("obligation-renew-prescription")


@pytest.fixture
def explainer(store: FirestoreGraphStore) -> JustificationExplainer:
    return JustificationExplainer(store)


class TestJustificationExplainer:
    def test_root_node_id_matches_input(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        assert result.root_node_id == str(O2_PRESCRIPTION)

    def test_root_step_has_no_via_edge(self, explainer: JustificationExplainer, seeded: SeedResult) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        root_steps = [s for s in result.steps if s.node_id == str(O2_PRESCRIPTION)]
        assert len(root_steps) == 1
        assert root_steps[0].depth == 0
        assert root_steps[0].via_edge is None

    def test_reaches_real_multi_hop_depth(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        depths = {s.depth for s in result.steps}
        # A genuine multi-hop chain, not a star graph around the root.
        assert max(depths) >= 3

    def test_every_via_edge_is_a_justificatory_edge_type(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        justificatory_values = {edge_type.value for edge_type in JUSTIFICATORY_EDGE_TYPES}
        for step in result.steps:
            if step.via_edge is not None:
                assert step.via_edge["type"] in justificatory_values

    def test_direct_document_reached_at_depth_one_with_region(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        """doc-pharmacy-sms is reached directly via the IMPLIES edge one
        hop from the root, and O2's own provenance.source_ref points at
        that exact document with region "msg-1" — the resolvable-region
        case."""
        result = explainer.explain(O2_PRESCRIPTION)
        pharmacy_doc_steps = [s for s in result.steps if s.node_id == "doc-pharmacy-sms"]
        assert pharmacy_doc_steps
        assert min(s.depth for s in pharmacy_doc_steps) == 1

        doc_by_id = {doc.id: doc for doc in result.source_documents}
        assert "doc-pharmacy-sms" in doc_by_id
        assert doc_by_id["doc-pharmacy-sms"].channel == "sms"
        assert doc_by_id["doc-pharmacy-sms"].region == "msg-1"

    def test_terminates_at_all_three_real_source_document_roots(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        doc_ids = {doc.id for doc in result.source_documents}
        assert doc_ids == {"doc-pharmacy-sms", "doc-freshmart-receipt", "doc-school-whatsapp"}

    def test_region_is_none_when_the_path_carries_no_resolvable_pointer(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        doc_by_id = {doc.id: doc for doc in result.source_documents}
        # branch-home-delivery's own provenance points at doc-pharmacy-sms,
        # not at doc-freshmart-receipt — the GROUNDED_IN edge to it carries
        # no resolvable region for *this* document.
        assert doc_by_id["doc-freshmart-receipt"].region is None

    def test_school_whatsapp_reached_via_conflicting_obligation_with_region(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION)
        doc_by_id = {doc.id: doc for doc in result.source_documents}
        assert doc_by_id["doc-school-whatsapp"].channel == "whatsapp"
        assert doc_by_id["doc-school-whatsapp"].region == "msg-9"

    def test_never_walks_a_non_justificatory_edge(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        """ABSENT_FROM (constraint-dadi-nap -> a document that was never
        written as a node) is reachable one hop from a node this walk does
        visit (constraint-dadi-nap, via VIOLATES) — proving the walk
        doesn't follow it also proves it never tries to resolve a
        deliberately-nonexistent node id."""
        result = explainer.explain(O2_PRESCRIPTION)
        visited_ids = {s.node_id for s in result.steps}
        assert "constraint-dadi-nap" in visited_ids
        assert "doc-expected-caregiver-log-never-arrived" not in visited_ids

    def test_unknown_node_id_raises_node_not_found(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        with pytest.raises(NodeNotFound):
            explainer.explain(NodeId("does-not-exist"))

    def test_max_depth_bound_is_respected(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION, max_depth=1)
        assert all(step.depth <= 1 for step in result.steps)
        # depth-1 neighbours are still found even with a tight cap.
        assert any(step.node_id == "doc-pharmacy-sms" for step in result.steps)

    def test_max_nodes_bound_is_respected(
        self, explainer: JustificationExplainer, seeded: SeedResult
    ) -> None:
        result = explainer.explain(O2_PRESCRIPTION, max_nodes=1)
        assert len(result.steps) == 1
        assert result.steps[0].node_id == str(O2_PRESCRIPTION)


def test_justificatory_edge_types_excludes_purely_structural_edges() -> None:
    excluded = {
        EdgeType.OWNED_BY,
        EdgeType.BENEFITS,
        EdgeType.CONSTRAINS,
        EdgeType.APPROVED_BY,
        EdgeType.SUPERSEDES,
        EdgeType.CONTAINS,
        EdgeType.CONCEDED_BY,
        EdgeType.BOOKED_WITH,
        EdgeType.SUBSTITUTES,
        EdgeType.EVIDENCES_EFFORT,
        EdgeType.ABSENT_FROM,
    }
    assert JUSTIFICATORY_EDGE_TYPES.isdisjoint(excluded)
    assert len(JUSTIFICATORY_EDGE_TYPES) == 22
