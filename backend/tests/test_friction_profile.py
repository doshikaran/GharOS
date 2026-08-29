"""Tests for `app.agents.intention_action.friction_profile` — ADR-015's
`CHARACTERIZES` edge write path, and PHASES.md Gate 9's literal checklist
item: **"correction updates the friction profile."**

This is real, tested code proving:
- A first correction of a kind creates a new `Pattern` (`support_count=1`)
  connected to the person via a real `CHARACTERIZES` edge.
- A repeat correction of the same kind increments an existing `Pattern`'s
  `support_count` via real supersession (a new node version, a
  `SUPERSEDES` edge back to the prior version, a fresh `CHARACTERIZES`
  edge to the person) — never an in-place mutation.
- `summarise_for_person` and `find_matching_pattern` read the real,
  written profile back correctly.

Unit tests only (`FakeGraphReader`/`FakeGraphWriter`/
`InMemoryIdempotencyStore` test doubles, no Firestore emulator needed for
this module's own logic — the real emulator-backed provenance/supersession
proof lives in `test_graph_write_tool.py`, which this module's writes flow
through unchanged).
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import EdgeType, NodeId, Pattern

from app.agents.intention_action import friction_profile
from app.agents.intention_action.blocker_diagnosis_agent import AGENT_ID as A23_ID
from app.agents.intention_action.types import BlockerDiagnosis, BlockerType, DiagnosisCorrection
from tests.conftest import make_provenance

from ._fake_graph_reader import FakeGraphReader
from ._fake_graph_writer import FakeGraphWriter
from ._fake_idempotency_store import InMemoryIdempotencyStore

_PERSON_ID = NodeId("person-aarav")


def _original_diagnosis(*, blocker_type: BlockerType) -> BlockerDiagnosis:
    return BlockerDiagnosis(
        obligation_id=NodeId("obligation-dentist"),
        person_id=_PERSON_ID,
        blocker_type=blocker_type,
        diagnosis_text="original diagnosis text",
        evidence=(),
        confidence=0.7,
        considered_alternative_types=(),
        is_rediagnosis=False,
        superseded_diagnosis_type=None,
        model_tier="pro",
        prompt_version="v1",
        invocation_id="inv-1",
        diagnosed_at=datetime(2026, 8, 1, tzinfo=UTC),
    )


def _correction(
    *, corrected_blocker_type: BlockerType, corrected_at: datetime = datetime(2026, 8, 2, tzinfo=UTC)
) -> DiagnosisCorrection:
    return DiagnosisCorrection(
        obligation_id=NodeId("obligation-dentist"),
        person_id=_PERSON_ID,
        original_diagnosis=_original_diagnosis(blocker_type=BlockerType.AVERSION),
        corrected_blocker_type=corrected_blocker_type,
        correction_note="no, this is actually an information blocker — the number was never obtained",
        corrected_by=NodeId("person-priya"),
        corrected_at=corrected_at,
    )


class TestFirstCorrectionCreatesNewPattern:
    def test_creates_a_pattern_with_support_count_one(self) -> None:
        reader = FakeGraphReader()
        writer = FakeGraphWriter()
        correction = _correction(corrected_blocker_type=BlockerType.INFORMATION)

        pattern_id = friction_profile.apply_diagnosis_correction(
            reader=reader,
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
            correction=correction,
            person_display_name="Aarav",
        )

        written = writer.nodes[pattern_id]
        assert isinstance(written, Pattern)
        assert written.support_count == 1
        assert written.provenance.deriving_agent == A23_ID
        # AMBIGUOUS, multi-source, per the ValuationProfile precedent:
        assert written.provenance.source_ref is None

    def test_writes_a_real_characterizes_edge_to_the_person(self) -> None:
        reader = FakeGraphReader()
        writer = FakeGraphWriter()
        correction = _correction(corrected_blocker_type=BlockerType.INFORMATION)

        pattern_id = friction_profile.apply_diagnosis_correction(
            reader=reader,
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
            correction=correction,
            person_display_name="Aarav",
        )

        characterizes_edges = [e for e in writer.edges if e.edge_type is EdgeType.CHARACTERIZES]
        assert len(characterizes_edges) == 1
        assert characterizes_edges[0].from_id == pattern_id
        assert characterizes_edges[0].to_id == _PERSON_ID

    def test_pattern_description_is_recoverable_as_the_real_blocker_type(self) -> None:
        reader = FakeGraphReader()
        writer = FakeGraphWriter()
        correction = _correction(corrected_blocker_type=BlockerType.INFORMATION)

        pattern_id = friction_profile.apply_diagnosis_correction(
            reader=reader,
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
            correction=correction,
            person_display_name="Aarav",
        )

        written = writer.nodes[pattern_id]
        assert isinstance(written, Pattern)
        assert friction_profile.extract_blocker_type_from_pattern(written) is BlockerType.INFORMATION


class TestRepeatCorrectionIncrementsExistingPattern:
    def test_second_correction_of_same_type_supersedes_with_incremented_support(self) -> None:
        # The "existing" pattern is built via a real first call to
        # `apply_diagnosis_correction` below, not hand-constructed, so its
        # description format matches exactly what this module itself
        # produces.
        reader = FakeGraphReader()
        writer = FakeGraphWriter()
        idempotency_store = InMemoryIdempotencyStore()

        first_correction = _correction(
            corrected_blocker_type=BlockerType.INFORMATION, corrected_at=datetime(2026, 8, 2, tzinfo=UTC)
        )
        first_pattern_id = friction_profile.apply_diagnosis_correction(
            reader=reader,
            graph_writer=writer,
            idempotency_store=idempotency_store,
            correction=first_correction,
            person_display_name="Aarav",
        )
        first_pattern = writer.nodes[first_pattern_id]
        assert isinstance(first_pattern, Pattern)

        # Wire the fake reader to now report the just-written pattern as
        # this person's existing CHARACTERIZES neighbour — real behaviour
        # a live Firestore-backed GraphReader would exhibit automatically.
        reader_with_existing = FakeGraphReader(
            neighbours_by_node_and_type={(str(_PERSON_ID), EdgeType.CHARACTERIZES): (first_pattern,)}
        )

        second_correction = _correction(
            corrected_blocker_type=BlockerType.INFORMATION, corrected_at=datetime(2026, 8, 15, tzinfo=UTC)
        )
        second_pattern_id = friction_profile.apply_diagnosis_correction(
            reader=reader_with_existing,
            graph_writer=writer,
            idempotency_store=idempotency_store,
            correction=second_correction,
            person_display_name="Aarav",
        )

        second_pattern = writer.nodes[second_pattern_id]
        assert isinstance(second_pattern, Pattern)
        assert second_pattern.support_count == 2
        assert second_pattern_id != first_pattern_id

        supersedes_edges = [e for e in writer.edges if e.edge_type is EdgeType.SUPERSEDES]
        assert len(supersedes_edges) == 1
        assert supersedes_edges[0].from_id == second_pattern_id
        assert supersedes_edges[0].to_id == first_pattern_id

        characterizes_edges = [e for e in writer.edges if e.edge_type is EdgeType.CHARACTERIZES]
        assert len(characterizes_edges) == 2  # one per correction — prior edge left in place, real history

    def test_different_blocker_type_creates_a_separate_pattern_not_an_increment(self) -> None:
        writer = FakeGraphWriter()
        idempotency_store = InMemoryIdempotencyStore()

        info_correction = _correction(corrected_blocker_type=BlockerType.INFORMATION)
        info_pattern_id = friction_profile.apply_diagnosis_correction(
            reader=FakeGraphReader(),
            graph_writer=writer,
            idempotency_store=idempotency_store,
            correction=info_correction,
            person_display_name="Aarav",
        )
        info_pattern = writer.nodes[info_pattern_id]
        assert isinstance(info_pattern, Pattern)

        reader_with_existing = FakeGraphReader(
            neighbours_by_node_and_type={(str(_PERSON_ID), EdgeType.CHARACTERIZES): (info_pattern,)}
        )
        aversion_correction = _correction(corrected_blocker_type=BlockerType.AVERSION)
        aversion_pattern_id = friction_profile.apply_diagnosis_correction(
            reader=reader_with_existing,
            graph_writer=writer,
            idempotency_store=idempotency_store,
            correction=aversion_correction,
            person_display_name="Aarav",
        )

        aversion_pattern = writer.nodes[aversion_pattern_id]
        assert isinstance(aversion_pattern, Pattern)
        assert aversion_pattern.support_count == 1
        assert aversion_pattern_id != info_pattern_id
        assert not any(e.edge_type is EdgeType.SUPERSEDES for e in writer.edges)


class TestFindMatchingPatternAndSummary:
    def test_find_matching_pattern_returns_none_when_absent(self) -> None:
        reader = FakeGraphReader()

        assert (
            friction_profile.find_matching_pattern(
                reader, person_id=_PERSON_ID, blocker_type=BlockerType.WINDOW
            )
            is None
        )

    def test_summarise_for_person_is_none_when_no_patterns(self) -> None:
        reader = FakeGraphReader()

        assert friction_profile.summarise_for_person(reader, person_id=_PERSON_ID) is None

    def test_summarise_for_person_lists_real_patterns(self) -> None:
        writer = FakeGraphWriter()
        pattern_id = friction_profile.apply_diagnosis_correction(
            reader=FakeGraphReader(),
            graph_writer=writer,
            idempotency_store=InMemoryIdempotencyStore(),
            correction=_correction(corrected_blocker_type=BlockerType.INFORMATION),
            person_display_name="Aarav",
        )
        pattern = writer.nodes[pattern_id]
        reader = FakeGraphReader(
            neighbours_by_node_and_type={(str(_PERSON_ID), EdgeType.CHARACTERIZES): (pattern,)}
        )

        summary = friction_profile.summarise_for_person(reader, person_id=_PERSON_ID)

        assert summary is not None
        assert "support: 1" in summary


def test_extract_blocker_type_from_pattern_returns_none_for_unrelated_pattern() -> None:
    unrelated = Pattern(
        id=NodeId("pattern-unrelated"),
        provenance=make_provenance(),
        description="This household reliably grocery-shops on Saturday mornings.",
        support_count=5,
        contributing_outcome_ids=(),
    )

    assert friction_profile.extract_blocker_type_from_pattern(unrelated) is None
