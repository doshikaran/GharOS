"""`FirestoreGraphReader.blast_radius_multi` and `.outcome_variance` —
Phase 11 additions (ADR-017), proven against the seeded demo household
(`seeds.demo_household`) exactly like the original 14 traversals in
`test_traversals.py`, plus extra nodes written atop the seed where a test
needs data the seed doesn't already carry (overlapping/non-overlapping
attribution tags across multiple entities, divergent multi-seed blast
radii).
"""

from __future__ import annotations

import pytest
from contracts.graph_types import (
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Outcome,
)

from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from seeds.demo_household import SeedResult
from tests.conftest import make_provenance

PRIYA = NodeId("person-priya")
AARAV = NodeId("person-aarav")
DADI = NodeId("person-dadi")
PICKUP = NodeId("obligation-pickup-aarav")
VENDOR_FRESHMART = NodeId("vendor-freshmart")

# ADR-017's own seeded decision-category OUTCOMEs (backend/seeds/
# demo_household.py) — one per tag, thin history by design.
SEEDED_SCHOOL_TRANSITION_OUTCOME = NodeId("outcome-aarav-school-admission")
SEEDED_STAFF_TRANSITION_OUTCOME = NodeId("outcome-maya-onboarding")
SEEDED_MAJOR_PURCHASE_OUTCOME = NodeId("outcome-water-purifier")


def _outcome(node_id: str, *, tags: tuple[str, ...], variance: float | None = 0.0) -> Outcome:
    return Outcome(
        id=NodeId(node_id),
        provenance=make_provenance(derivation=Derivation.INFERRED, confidence=0.8),
        predicted="predicted",
        actual="actual",
        variance=variance,
        attribution_tags=tags,
    )


def _completes_into(edge_id: str, from_id: NodeId, to_id: NodeId) -> Edge:
    return Edge(
        id=EdgeId(edge_id),
        provenance=make_provenance(),
        edge_type=EdgeType.COMPLETES_INTO,
        from_id=from_id,
        to_id=to_id,
    )


class TestOutcomeVariance:
    def test_empty_result_for_a_tag_nothing_carries(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        assert reader.outcome_variance("relocation") == ()

    def test_matches_the_seeded_outcome_by_its_existing_tag(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        """The seed's own `outcome-prescription-delivered` already carries
        `attribution_tags=("on-time", "no-conflict")` (Phase 10's
        provider-reliability vocabulary) — proving `outcome_variance`
        finds it confirms the same field serves both tag vocabularies, per
        ADR-017's "one field, two conventions, distinguished by value"."""
        found = reader.outcome_variance("on-time")
        assert {o.id for o in found} == {NodeId("outcome-prescription-delivered")}

    def test_cross_entity_aggregation_overlapping_and_non_overlapping_tags(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, seeded: SeedResult
    ) -> None:
        """Three new OUTCOMEs, each completing from a *different* seeded
        entity, with a mix of shared and distinct tags — proves the scan
        is genuinely cross-entity (not `history(entity)` in disguise) and
        that overlapping tags on different entities are all found while
        non-overlapping ones are correctly excluded.

        `seeds.demo_household` itself now also carries one real
        `"major_purchase"`/`"school_transition"`/`"staff_transition"`-
        tagged OUTCOME each (ADR-017's own thin, honest seed history) —
        this test's expectations include those seeded ids explicitly
        rather than asserting emptiness where the seed itself now
        contributes a real match; the point being proven (cross-entity
        aggregation, overlap, non-overlap) is unaffected either way."""
        relocation_a = _outcome("outcome-relocation-a", tags=("relocation", "major_purchase"))
        relocation_b = _outcome("outcome-relocation-b", tags=("relocation",))
        staff_c = _outcome("outcome-staff-c", tags=("staff_transition",))
        for node in (relocation_a, relocation_b, staff_c):
            writer.write_node(node)
        writer.write_edge(_completes_into("e-o1-reloc-a", PICKUP, relocation_a.id))
        writer.write_edge(
            _completes_into("e-o7-reloc-b", NodeId("obligation-pay-maya-salary"), relocation_b.id)
        )
        writer.write_edge(
            _completes_into("e-o6-staff-c", NodeId("obligation-weekly-groceries"), staff_c.id)
        )

        # relocation: no seeded outcome carries this tag (the household has
        # never relocated — ADR-017's own seed docstring) so only the two
        # newly-written entities match.
        relocation_found = reader.outcome_variance("relocation")
        assert {o.id for o in relocation_found} == {relocation_a.id, relocation_b.id}

        # major_purchase: overlaps between the newly-written entity and the
        # seed's own real "outcome-water-purifier" — genuine cross-entity
        # aggregation of *pre-existing graph data plus new writes*.
        major_purchase_found = reader.outcome_variance("major_purchase")
        assert {o.id for o in major_purchase_found} == {relocation_a.id, SEEDED_MAJOR_PURCHASE_OUTCOME}

        staff_found = reader.outcome_variance("staff_transition")
        assert {o.id for o in staff_found} == {staff_c.id, SEEDED_STAFF_TRANSITION_OUTCOME}

        # non-overlapping: a school_transition query must not pick up any
        # of the three newly-written entities above (none carry that tag)
        # — only the seed's own pre-existing school_transition outcome.
        school_transition_found = reader.outcome_variance("school_transition")
        assert {o.id for o in school_transition_found} == {SEEDED_SCHOOL_TRANSITION_OUTCOME}

    def test_unresolved_variance_outcomes_are_still_returned(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter, seeded: SeedResult
    ) -> None:
        """`outcome_variance` is a graph read, not a calibration
        computation — an OUTCOME whose real-world result is not yet
        settled (`variance=None`) still belongs in the returned tuple;
        excluding unresolved outcomes from statistics is
        `calibration_stats.compute_calibration`'s job, not this method's."""
        pending = _outcome("outcome-pending-relocation", tags=("relocation",), variance=None)
        writer.write_node(pending)
        writer.write_edge(_completes_into("e-o1-pending-reloc", PICKUP, pending.id))

        found = reader.outcome_variance("relocation")
        assert pending.id in {o.id for o in found}
        matched = next(o for o in found if o.id == pending.id)
        assert matched.variance is None


class TestBlastRadiusMultiEquivalence:
    """Literal proof of correctness-equivalence to calling `blast_radius`
    once per seed and unioning by node id — not a spot check."""

    @pytest.mark.parametrize(
        ("seed_ids", "depth"),
        [
            ((PICKUP,), 0),
            ((PICKUP,), 1),
            ((PICKUP,), 3),
            ((PICKUP, VENDOR_FRESHMART), 0),
            ((PICKUP, VENDOR_FRESHMART), 1),
            ((PICKUP, VENDOR_FRESHMART), 2),
            ((PICKUP, VENDOR_FRESHMART), 3),
            ((PRIYA, DADI), 1),
            ((PRIYA, DADI), 2),
            ((PRIYA, DADI, VENDOR_FRESHMART), 2),
            ((PRIYA, PRIYA), 1),  # duplicate seed tolerated
        ],
    )
    def test_equivalent_to_union_of_individual_blast_radius_calls(
        self,
        reader: FirestoreGraphReader,
        seeded: SeedResult,
        seed_ids: tuple[NodeId, ...],
        depth: int,
    ) -> None:
        expected_ids: set[NodeId] = set()
        for seed in seed_ids:
            expected_ids |= {n.id for n in reader.blast_radius(seed, depth)}  # type: ignore[attr-defined]

        multi_ids = {n.id for n in reader.blast_radius_multi(seed_ids, depth)}  # type: ignore[attr-defined]
        assert multi_ids == expected_ids


class TestBlastRadiusMultiBehaviour:
    def test_depth_zero_is_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.blast_radius_multi((PICKUP, VENDOR_FRESHMART), depth=0) == ()

    def test_negative_depth_is_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.blast_radius_multi((PICKUP,), depth=-1) == ()

    def test_empty_seed_tuple_is_empty(self, reader: FirestoreGraphReader, seeded: SeedResult) -> None:
        assert reader.blast_radius_multi((), depth=3) == ()

    def test_seed_nodes_are_never_included_in_their_own_result(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        reached = reader.blast_radius_multi((PICKUP, VENDOR_FRESHMART), depth=2)
        ids = {n.id for n in reached}  # type: ignore[attr-defined]
        assert PICKUP not in ids
        assert VENDOR_FRESHMART not in ids

    def test_divergent_reachable_sets_union_exceeds_either_seed_alone(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        """Two seeds on genuinely different parts of the seeded graph
        (Priya's obligation-heavy neighbourhood vs. the grocery vendor's
        ledger-event neighbourhood) — the multi-seed union must be a
        proper superset of what either seed reaches alone, proving this is
        real union behaviour and not accidentally just one seed's radius."""
        depth = 1
        priya_alone = {n.id for n in reader.blast_radius(PRIYA, depth)}  # type: ignore[attr-defined]
        vendor_alone = {n.id for n in reader.blast_radius(VENDOR_FRESHMART, depth)}  # type: ignore[attr-defined]
        assert priya_alone, "expected Priya to reach at least one node at depth 1"
        assert vendor_alone, "expected the grocery vendor to reach at least one node at depth 1"
        # genuinely divergent: neither seed's own reachable set contains
        # the other seed's node at this depth
        assert VENDOR_FRESHMART not in priya_alone
        assert PRIYA not in vendor_alone

        union = {n.id for n in reader.blast_radius_multi((PRIYA, VENDOR_FRESHMART), depth)}  # type: ignore[attr-defined]
        assert union == priya_alone | vendor_alone
        assert len(union) > len(priya_alone)
        assert len(union) > len(vendor_alone)

    def test_depth_boundary_a_node_reachable_only_at_greater_depth_is_excluded(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        """Finds the real minimum depth `D` at which `PICKUP`'s own single-
        seed `blast_radius` first reaches `provider-mehta-pharmacy` (rather
        than hard-assuming a specific hop count, which would make this
        test fragile to unrelated seed-data edits), then confirms
        `blast_radius_multi((PICKUP,), depth)` honours the exact same
        boundary: absent at `D - 1`, present at `D`."""
        target = NodeId("provider-mehta-pharmacy")
        min_depth = next(
            d
            for d in range(1, 10)
            if target in {n.id for n in reader.blast_radius(PICKUP, d)}  # type: ignore[attr-defined]
        )
        assert min_depth > 1, "test assumes a real multi-hop boundary exists to check"

        shallow = {n.id for n in reader.blast_radius_multi((PICKUP,), depth=min_depth - 1)}  # type: ignore[attr-defined]
        at_boundary = {n.id for n in reader.blast_radius_multi((PICKUP,), depth=min_depth)}  # type: ignore[attr-defined]
        assert target not in shallow
        assert target in at_boundary

    def test_unknown_seed_id_is_tolerated_and_contributes_nothing(
        self, reader: FirestoreGraphReader, seeded: SeedResult
    ) -> None:
        real_only = {n.id for n in reader.blast_radius(PICKUP, 2)}  # type: ignore[attr-defined]
        with_unknown = {
            n.id  # type: ignore[attr-defined]
            for n in reader.blast_radius_multi((PICKUP, NodeId("does-not-exist")), depth=2)
        }
        assert with_unknown == real_only
