"""Tests for `app.solvers.conflict_prepass.DeterministicConflictPrepass`
(PHASES.md Phase 4, E1 work item 1; spec §7.3 Stage 3).

Every scenario is built against the real Firestore emulator via the
`reader`/`writer` fixtures (gharos-standards: integration tests against
the emulator, not mocks) — including the exact canonical field-trip
scenario spec §7.3's worked example and PHASES.md Gate 4 both name: a
1:30pm early pickup colliding with a 1:00pm work meeting. This is the
fixture E2's A14 Gate 4 acceptance test needs to see caught by this same
deterministic pre-pass.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from contracts.graph_types import (
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Person,
)

from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.solvers.conflict_prepass import (
    ConflictType,
    DeterministicConflictPrepass,
    ResourceIdentityResolver,
)
from tests.conftest import NOW, make_person, make_provenance

_WIDE_WINDOW = (NOW - timedelta(days=1), NOW + timedelta(days=1))
_HIGH_THRESHOLD_MINUTES = 10_000.0
"""Effectively "never trips" — used by tests that are not exercising the
load-conflict path, so `run()` never returns a spurious LoadConflict."""


def _obligation(
    node_id: str,
    title: str,
    *,
    due_at: datetime | None,
    effort_estimate_minutes: int | None,
    obligation_type: str = "errand",
    status: ObligationStatus = ObligationStatus.ASSIGNED,
) -> Obligation:
    return Obligation(
        id=NodeId(node_id),
        provenance=make_provenance(),
        title=title,
        obligation_type=obligation_type,
        due_at=due_at,
        must_start_by=None,
        effort_estimate_minutes=effort_estimate_minutes,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _own(writer: FirestoreGraphWriter, edge_id: str, obligation_id: NodeId, person_id: NodeId) -> None:
    writer.write_edge(
        Edge(
            id=EdgeId(edge_id),
            provenance=make_provenance(),
            edge_type=EdgeType.OWNED_BY,
            from_id=obligation_id,
            to_id=person_id,
        )
    )


def _write_person(
    writer: FirestoreGraphWriter,
    *,
    node_id: str,
    display_name: str,
    can_drive: bool = False,
    can_sign: bool = False,
    has_bank_access: bool = False,
) -> Person:
    person = make_person(
        node_id,
        display_name,
        can_drive=can_drive,
        can_sign=can_sign,
        has_bank_access=has_bank_access,
    )
    writer.write_node(person)
    return person


class TestTemporalConflict:
    def test_field_trip_pickup_vs_work_meeting_detected(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        """Spec §7.3's canonical field-trip example, PHASES.md Gate 4:
        "Temporal collision (1:30 pickup vs 1:00 meeting) detected."
        Meeting runs 1:00pm-2:00pm (due_at=14:00, effort=60); the early
        pickup needs Priya from 1:15pm to 1:30pm (due_at=13:30, effort=15)
        — squarely inside the meeting window."""
        priya = _write_person(writer, node_id="person-priya-fieldtrip", display_name="Priya")

        meeting = _obligation(
            "obligation-work-meeting",
            "1:00pm work meeting",
            due_at=NOW.replace(hour=14, minute=0),
            effort_estimate_minutes=60,
        )
        pickup = _obligation(
            "obligation-early-pickup",
            "Early pickup - field trip",
            due_at=NOW.replace(hour=13, minute=30),
            effort_estimate_minutes=15,
        )
        writer.write_node(meeting)
        writer.write_node(pickup)
        _own(writer, "e-own-meeting", meeting.id, priya.id)
        _own(writer, "e-own-pickup", pickup.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [meeting, pickup],
            fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES,
            load_window=_WIDE_WINDOW,
        )

        assert len(result.temporal) == 1
        conflict = result.temporal[0]
        assert conflict.conflict_type is ConflictType.TEMPORAL
        assert conflict.person_id == priya.id
        assert {conflict.obligation_a_id, conflict.obligation_b_id} == {meeting.id, pickup.id}
        assert conflict.overlap == (
            NOW.replace(hour=13, minute=15),
            NOW.replace(hour=13, minute=30),
        )

    def test_different_owners_no_conflict(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-diff", display_name="Priya")
        aarav = _write_person(writer, node_id="person-aarav-diff", display_name="Aarav")

        a = _obligation(
            "obligation-diff-a", "A", due_at=NOW.replace(hour=13, minute=0), effort_estimate_minutes=60
        )
        b = _obligation(
            "obligation-diff-b", "B", due_at=NOW.replace(hour=13, minute=30), effort_estimate_minutes=15
        )
        writer.write_node(a)
        writer.write_node(b)
        _own(writer, "e-own-diff-a", a.id, priya.id)
        _own(writer, "e-own-diff-b", b.id, aarav.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [a, b], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.temporal == ()

    def test_touching_windows_are_adjacent_not_overlapping(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-touch", display_name="Priya")
        first = _obligation(
            "obligation-touch-a", "First", due_at=NOW.replace(hour=10, minute=0), effort_estimate_minutes=60
        )
        second = _obligation(
            "obligation-touch-b",
            "Second",
            due_at=NOW.replace(hour=11, minute=0),
            effort_estimate_minutes=60,
        )
        writer.write_node(first)
        writer.write_node(second)
        _own(writer, "e-own-touch-a", first.id, priya.id)
        _own(writer, "e-own-touch-b", second.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [first, second], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.temporal == ()

    def test_missing_due_at_is_skipped(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-nodue", display_name="Priya")
        no_due = _obligation("obligation-no-due", "No due date", due_at=None, effort_estimate_minutes=30)
        dated = _obligation("obligation-has-due", "Has a due date", due_at=NOW, effort_estimate_minutes=30)
        writer.write_node(no_due)
        writer.write_node(dated)
        _own(writer, "e-own-nodue-a", no_due.id, priya.id)
        _own(writer, "e-own-nodue-b", dated.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [no_due, dated], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.temporal == ()

    def test_point_events_use_due_at_as_a_zero_width_window(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        """No `effort_estimate_minutes` collapses the window to a single
        point at `due_at` — that point still conflicts if it falls
        strictly inside another obligation's window."""
        priya = _write_person(writer, node_id="person-priya-point", display_name="Priya")
        meeting = _obligation(
            "obligation-point-meeting",
            "Meeting",
            due_at=NOW.replace(hour=14, minute=0),
            effort_estimate_minutes=60,
        )
        instant = _obligation(
            "obligation-point-instant",
            "A call at exactly 1:30",
            due_at=NOW.replace(hour=13, minute=30),
            effort_estimate_minutes=None,
        )
        writer.write_node(meeting)
        writer.write_node(instant)
        _own(writer, "e-own-point-a", meeting.id, priya.id)
        _own(writer, "e-own-point-b", instant.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [meeting, instant], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert len(result.temporal) == 1


class _FixedResourceResolver:
    """Test double for `ResourceIdentityResolver` — maps specific
    obligation ids to a resource key, exactly as a real caller would once
    it has some other source of truth for resource identity."""

    def __init__(self, mapping: dict[NodeId, str]) -> None:
        self._mapping = mapping

    def resolve(self, obligation: Obligation) -> str | None:
        return self._mapping.get(obligation.id)


def _resource_resolver_conforms(mapping: dict[NodeId, str]) -> ResourceIdentityResolver:
    """Structural-conformance check (mypy --strict, same pattern as
    `app.graph.conformance`): if `_FixedResourceResolver` ever drifts from
    `ResourceIdentityResolver`'s shape, this line fails type-checking."""
    return _FixedResourceResolver(mapping)


class TestResourceConflict:
    def test_no_resolver_skips_detection_and_flags_it(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-noresolver", display_name="Priya")
        a = _obligation(
            "obligation-res-noresolver-a",
            "Drive to airport",
            due_at=NOW.replace(hour=9, minute=0),
            effort_estimate_minutes=60,
        )
        b = _obligation(
            "obligation-res-noresolver-b",
            "Drive to school",
            due_at=NOW.replace(hour=9, minute=30),
            effort_estimate_minutes=60,
        )
        writer.write_node(a)
        writer.write_node(b)
        _own(writer, "e-own-res-noresolver-a", a.id, priya.id)
        _own(writer, "e-own-res-noresolver-b", b.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)  # no resolver injected
        result = prepass.run(
            [a, b], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.resource == ()
        assert result.resource_detection_skipped is True

    def test_injected_resolver_detects_overlapping_resource_use(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-res", display_name="Priya")
        aarav = _write_person(writer, node_id="person-aarav-res", display_name="Aarav")

        a = _obligation(
            "obligation-res-a",
            "Drive to airport",
            due_at=NOW.replace(hour=9, minute=0),
            effort_estimate_minutes=60,
        )
        b = _obligation(
            "obligation-res-b",
            "Drive to school",
            due_at=NOW.replace(hour=9, minute=30),
            effort_estimate_minutes=60,
        )
        writer.write_node(a)
        writer.write_node(b)
        _own(writer, "e-own-res-a", a.id, priya.id)
        _own(writer, "e-own-res-b", b.id, aarav.id)

        resolver = _resource_resolver_conforms({a.id: "vehicle:family-car", b.id: "vehicle:family-car"})
        prepass = DeterministicConflictPrepass(reader, resource_identity_resolver=resolver)
        result = prepass.run(
            [a, b], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )

        assert result.resource_detection_skipped is False
        assert len(result.resource) == 1
        conflict = result.resource[0]
        assert conflict.conflict_type is ConflictType.RESOURCE
        assert conflict.resource_key == "vehicle:family-car"
        assert {conflict.obligation_a_id, conflict.obligation_b_id} == {a.id, b.id}

    def test_different_resources_no_conflict(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-res2", display_name="Priya")
        a = _obligation(
            "obligation-res2-a",
            "Drive to airport",
            due_at=NOW.replace(hour=9, minute=0),
            effort_estimate_minutes=60,
        )
        b = _obligation(
            "obligation-res2-b",
            "Use the ladder",
            due_at=NOW.replace(hour=9, minute=30),
            effort_estimate_minutes=60,
        )
        writer.write_node(a)
        writer.write_node(b)
        _own(writer, "e-own-res2-a", a.id, priya.id)
        _own(writer, "e-own-res2-b", b.id, priya.id)

        resolver = _resource_resolver_conforms({a.id: "vehicle:family-car", b.id: "tool:ladder"})
        prepass = DeterministicConflictPrepass(reader, resource_identity_resolver=resolver)
        result = prepass.run(
            [a, b], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.resource == ()


class TestCapabilityConflict:
    def test_permission_slip_owner_without_can_sign_detected(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        child = _write_person(writer, node_id="person-aarav-cap", display_name="Aarav", can_sign=False)
        slip = _obligation(
            "obligation-cap-slip",
            "Sign & return: field trip consent",
            due_at=NOW,
            effort_estimate_minutes=5,
            obligation_type="permission_slip",
        )
        writer.write_node(slip)
        _own(writer, "e-own-cap-slip", slip.id, child.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [slip], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )

        assert len(result.capability) == 1
        conflict = result.capability[0]
        assert conflict.conflict_type is ConflictType.CAPABILITY
        assert conflict.person_id == child.id
        assert conflict.obligation_id == slip.id
        assert conflict.missing_capability == "can_sign"

    def test_permission_slip_owner_with_can_sign_no_conflict(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        parent = _write_person(writer, node_id="person-priya-cap-ok", display_name="Priya", can_sign=True)
        slip = _obligation(
            "obligation-cap-slip-ok",
            "Sign & return: field trip consent",
            due_at=NOW,
            effort_estimate_minutes=5,
            obligation_type="permission_slip",
        )
        writer.write_node(slip)
        _own(writer, "e-own-cap-slip-ok", slip.id, parent.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [slip], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.capability == ()

    def test_unmapped_obligation_type_never_flags_a_capability(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        """`errand` has no default capability requirement — this module
        fabricates none beyond the one spec-grounded mapping."""
        person = _write_person(
            writer,
            node_id="person-cap-unmapped",
            display_name="Someone",
            can_drive=False,
            can_sign=False,
            has_bank_access=False,
        )
        errand = _obligation("obligation-cap-unmapped", "Buy milk", due_at=NOW, effort_estimate_minutes=10)
        writer.write_node(errand)
        _own(writer, "e-own-cap-unmapped", errand.id, person.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [errand], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )
        assert result.capability == ()

    def test_injected_capability_requirements_extend_the_default_mapping(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        person = _write_person(
            writer, node_id="person-cap-injected", display_name="Someone", has_bank_access=False
        )
        payment = _obligation(
            "obligation-cap-injected",
            "Pay society maintenance",
            due_at=NOW,
            effort_estimate_minutes=10,
            obligation_type="payment",
        )
        writer.write_node(payment)
        _own(writer, "e-own-cap-injected", payment.id, person.id)

        prepass = DeterministicConflictPrepass(
            reader, capability_requirements={"permission_slip": "can_sign", "payment": "has_bank_access"}
        )
        result = prepass.run(
            [payment], fairness_threshold_minutes=_HIGH_THRESHOLD_MINUTES, load_window=_WIDE_WINDOW
        )

        assert len(result.capability) == 1
        assert result.capability[0].missing_capability == "has_bank_access"


class TestLoadConflict:
    def test_exceeds_threshold_detected(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-load", display_name="Priya")
        heavy = _obligation(
            "obligation-load-heavy", "A very long errand", due_at=NOW, effort_estimate_minutes=120
        )
        writer.write_node(heavy)
        _own(writer, "e-own-load-heavy", heavy.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run([heavy], fairness_threshold_minutes=60.0, load_window=_WIDE_WINDOW)

        assert len(result.load) == 1
        conflict = result.load[0]
        assert conflict.conflict_type is ConflictType.LOAD
        assert conflict.person_id == priya.id
        assert conflict.load_minutes == 120.0
        assert conflict.threshold_minutes == 60.0
        assert conflict.exceeded_by_minutes == 60.0

    def test_within_threshold_no_conflict(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-load-ok", display_name="Priya")
        light = _obligation("obligation-load-light", "A short errand", due_at=NOW, effort_estimate_minutes=10)
        writer.write_node(light)
        _own(writer, "e-own-load-light", light.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run([light], fairness_threshold_minutes=60.0, load_window=_WIDE_WINDOW)
        assert result.load == ()


class TestConflictPrepassResultAggregation:
    def test_all_candidates_concatenates_in_stable_order(
        self, reader: FirestoreGraphReader, writer: FirestoreGraphWriter
    ) -> None:
        priya = _write_person(writer, node_id="person-priya-agg", display_name="Priya", can_sign=False)
        meeting = _obligation(
            "obligation-agg-meeting",
            "Meeting",
            due_at=NOW.replace(hour=14, minute=0),
            effort_estimate_minutes=120,
        )
        pickup = _obligation(
            "obligation-agg-pickup",
            "Pickup",
            due_at=NOW.replace(hour=13, minute=30),
            effort_estimate_minutes=15,
        )
        slip = _obligation(
            "obligation-agg-slip",
            "Sign slip",
            due_at=NOW,
            effort_estimate_minutes=5,
            obligation_type="permission_slip",
        )
        for node in (meeting, pickup, slip):
            writer.write_node(node)
        _own(writer, "e-own-agg-meeting", meeting.id, priya.id)
        _own(writer, "e-own-agg-pickup", pickup.id, priya.id)
        _own(writer, "e-own-agg-slip", slip.id, priya.id)

        prepass = DeterministicConflictPrepass(reader)
        result = prepass.run(
            [meeting, pickup, slip], fairness_threshold_minutes=1.0, load_window=_WIDE_WINDOW
        )

        all_candidates = result.all_candidates()
        expected_total = (
            len(result.temporal) + len(result.resource) + len(result.capability) + len(result.load)
        )
        assert len(all_candidates) == expected_total
        assert len(result.temporal) == 1
        assert len(result.capability) == 1
        assert len(result.load) == 1

        # documented order: temporal, then resource, then capability, then load.
        type_order = [
            ConflictType.TEMPORAL,
            ConflictType.RESOURCE,
            ConflictType.CAPABILITY,
            ConflictType.LOAD,
        ]
        rank_by_type = {t: i for i, t in enumerate(type_order)}
        ranks_seen = [rank_by_type[c.conflict_type] for c in all_candidates]
        assert ranks_seen == sorted(ranks_seen)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
