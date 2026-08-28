"""Tests for `app.tools.booking_write_tool` — the verification-gated T3
graph write that closes the Outbound Concierge loop (PHASES.md Phase 10).

Gate 10's own CTO review, made literal here: "is there any code path
writing a booking without verification? If yes, the phase fails."
`TestVerificationBoundary` and `TestBookingWriteToolNeverAcceptsAnythingElse`
are this file's adversarial proof of that — attempting every plausible
way a caller could try to skip verification, and showing each one fails
before any graph write happens.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    NodeId,
    Obligation,
    ObligationDerivation,
    ObligationStatus,
    Outcome,
    Provenance,
    SourceRef,
)
from contracts.tools import PermissionTier

from app.agents.concierge.types import CallOutcomeReport, VerifiedBooking
from app.graph.reader import FirestoreGraphReader
from app.graph.writer import FirestoreGraphWriter
from app.persistence.idempotency_store import FirestoreIdempotencyStore
from app.tools.booking_write_tool import (
    BookingNotVerified,
    BookingWriteTool,
    verified_booking_from_verification,
)
from tests._fake_idempotency_store import InMemoryIdempotencyStore

NOW = datetime(2026, 9, 3, 12, 0, tzinfo=UTC)
CONFIRMED_SLOT = datetime(2026, 9, 10, 16, 0, tzinfo=UTC)


def _obligation(status: ObligationStatus = ObligationStatus.ASSIGNED) -> Obligation:
    return Obligation(
        id=NodeId("obligation-dentist"),
        provenance=Provenance(
            derivation=Derivation.INFERRED,
            source_ref=SourceRef(source_document_id=NodeId("doc-request"), region="p1"),
            confidence=0.9,
            deriving_agent=AgentId("A50"),
            created_at=NOW,
        ),
        title="Book a routine dental cleaning for Aarav",
        obligation_type="appointment_booking",
        due_at=None,
        must_start_by=None,
        effort_estimate_minutes=15,
        status=status,
        stated_or_implied=ObligationDerivation.STATED,
    )


def _verified_booking(**overrides: object) -> VerifiedBooking:
    base: dict[str, object] = {
        "call_id": "call-1",
        "obligation_id": NodeId("obligation-dentist"),
        "person_id": NodeId("person-aarav"),
        "target_provider_id": NodeId("provider-1"),
        "transcript_source_document_id": NodeId("doc-transcript"),
        "confirmed_slot": CONFIRMED_SLOT,
        "confirmed_price": 1500.0,
        "attribution_tags": ("on_time",),
        "verified_by_agent": AgentId("A55"),
        "verified_at": NOW,
    }
    base.update(overrides)
    return VerifiedBooking(**base)  # type: ignore[arg-type]


class TestVerifiedBookingFromVerificationFactory:
    """`verified_booking_from_verification` is the *only* sanctioned
    constructor of a `VerifiedBooking` — see module docstring."""

    def test_verified_true_and_a_real_confirmed_slot_succeeds(self) -> None:
        booking = verified_booking_from_verification(
            verified=True,
            call_id="call-1",
            obligation_id=NodeId("obligation-dentist"),
            person_id=NodeId("person-aarav"),
            target_provider_id=NodeId("provider-1"),
            transcript_source_document_id=NodeId("doc-transcript"),
            confirmed_slot=CONFIRMED_SLOT,
            confirmed_price=1500.0,
            attribution_tags=("on_time",),
            verified_by_agent=AgentId("A55"),
            now=NOW,
        )
        assert isinstance(booking, VerifiedBooking)
        assert booking.confirmed_slot == CONFIRMED_SLOT

    def test_verified_false_raises_booking_not_verified(self) -> None:
        with pytest.raises(BookingNotVerified):
            verified_booking_from_verification(
                verified=False,
                call_id="call-2",
                obligation_id=NodeId("obligation-dentist"),
                person_id=NodeId("person-aarav"),
                target_provider_id=NodeId("provider-1"),
                transcript_source_document_id=NodeId("doc-transcript"),
                confirmed_slot=CONFIRMED_SLOT,
                confirmed_price=None,
                attribution_tags=(),
                verified_by_agent=AgentId("A55"),
            )

    def test_verified_true_but_no_confirmed_slot_raises_booking_not_verified(self) -> None:
        with pytest.raises(BookingNotVerified):
            verified_booking_from_verification(
                verified=True,
                call_id="call-3",
                obligation_id=NodeId("obligation-dentist"),
                person_id=NodeId("person-aarav"),
                target_provider_id=NodeId("provider-1"),
                transcript_source_document_id=NodeId("doc-transcript"),
                confirmed_slot=None,
                confirmed_price=None,
                attribution_tags=(),
                verified_by_agent=AgentId("A55"),
            )

    def test_a_realistic_unverified_outcome_from_a_call_report_cannot_be_booked(self) -> None:
        """The adversarial, end-to-end shaped proof: a genuine
        `CallOutcomeReport` that never resulted in a booking (out-of-bounds
        or escalated) can never be turned into a `VerifiedBooking`, even
        if a caller tries to smuggle its fields through."""
        unresolved_call = CallOutcomeReport(
            call_id="call-4",
            target_provider_id=NodeId("provider-1"),
            transcript_source_document_id=NodeId("doc-transcript"),
            disclosure_given=True,
            claimed_slot=None,
            claimed_outcome_summary="Clinic could not offer anything within bounds.",
            out_of_bounds_encountered=True,
            requires_human_callback=True,
        )
        with pytest.raises(BookingNotVerified):
            verified_booking_from_verification(
                verified=False,
                call_id=unresolved_call.call_id,
                obligation_id=NodeId("obligation-dentist"),
                person_id=NodeId("person-aarav"),
                target_provider_id=unresolved_call.target_provider_id,
                transcript_source_document_id=unresolved_call.transcript_source_document_id,
                confirmed_slot=unresolved_call.claimed_slot,
                confirmed_price=None,
                attribution_tags=(),
                verified_by_agent=AgentId("A55"),
            )


class TestBookingWriteToolNeverAcceptsAnythingElse:
    """`invoke_idempotent` only ever accepts a real `VerifiedBooking` via
    its `booking` kwarg — proven against every plausible substitute."""

    def test_missing_booking_kwarg_raises_tool_failure(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("key-1")

    def test_a_plain_dict_is_rejected_not_written(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        fake_booking = {
            "call_id": "call-5",
            "obligation_id": "obligation-dentist",
            "confirmed_slot": CONFIRMED_SLOT,
            "verified": True,
        }
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("key-2", booking=fake_booking)

    def test_a_raw_call_outcome_report_is_rejected_not_written(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        """The exact adversarial case Gate 10 asks for: a real
        `CallOutcomeReport` (A54's own output) is never, by itself,
        sufficient to write a booking — it has not been verified."""
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        report = CallOutcomeReport(
            call_id="call-6",
            target_provider_id=NodeId("provider-1"),
            transcript_source_document_id=NodeId("doc-transcript"),
            disclosure_given=True,
            claimed_slot=CONFIRMED_SLOT,
            claimed_outcome_summary="Agent believes it booked this slot.",
            out_of_bounds_encountered=False,
            requires_human_callback=False,
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("key-3", booking=report)


class TestSuccessfulWrite:
    def test_writes_a_real_outcome_node(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        writer.write_node(_obligation())
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        result = tool.invoke_idempotent("key-4", booking=_verified_booking())

        assert result.ok is True
        outcome = reader.get_node(NodeId(str(result.value)))
        assert isinstance(outcome, Outcome)
        assert outcome.attribution_tags == ("on_time",)
        assert "provider-1" in outcome.actual
        assert "1500.00" in outcome.actual

    def test_obligation_is_superseded_to_completed(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        writer.write_node(_obligation(status=ObligationStatus.ASSIGNED))
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        tool.invoke_idempotent("key-5", booking=_verified_booking())

        updated = reader.get_node(NodeId("obligation-dentist"))
        assert isinstance(updated, Obligation)
        assert updated.status is ObligationStatus.COMPLETED
        assert updated.title == "Book a routine dental cleaning for Aarav", (
            "every other field must be preserved"
        )

    def test_booked_with_and_completes_into_edges_are_written(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        from contracts.graph_types import EdgeType, Provider

        writer.write_node(_obligation())
        writer.write_node(
            Provider(
                id=NodeId("provider-1"),
                provenance=_obligation().provenance,
                name="Sunrise Dental",
                category="dentist",
                rating=4.6,
                distance_km=1.2,
                availability_notes=None,
                price_band="$$",
                specialisations=(),
            )
        )
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        result = tool.invoke_idempotent("key-6", booking=_verified_booking())

        booked_with = reader.neighbours(NodeId("obligation-dentist"), EdgeType.BOOKED_WITH)
        provider_ids = {str(node.id) for node in booked_with if isinstance(node, Provider)}
        assert "provider-1" in provider_ids

        completes_into = reader.neighbours(NodeId("obligation-dentist"), EdgeType.COMPLETES_INTO)
        outcome_ids = {str(node.id) for node in completes_into if isinstance(node, Outcome)}
        assert str(result.value) in outcome_ids

    def test_unknown_obligation_raises_tool_failure(
        self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader
    ) -> None:
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        with pytest.raises(ToolFailure):
            tool.invoke_idempotent("key-7", booking=_verified_booking(obligation_id=NodeId("does-not-exist")))


class TestReplaySafety:
    def test_second_call_with_same_key_is_a_no_op(
        self,
        writer: FirestoreGraphWriter,
        reader: FirestoreGraphReader,
        idempotency_store: FirestoreIdempotencyStore,
    ) -> None:
        writer.write_node(_obligation())
        tool = BookingWriteTool(graph_writer=writer, graph_reader=reader, idempotency_store=idempotency_store)
        key = "key-8"

        first = tool.invoke_idempotent(key, booking=_verified_booking())
        second = tool.invoke_idempotent(key, booking=_verified_booking())

        assert first.ok is True
        assert second.value == first.value


class TestToolIdentity:
    def test_tier_is_t3(self, writer: FirestoreGraphWriter, reader: FirestoreGraphReader) -> None:
        tool = BookingWriteTool(
            graph_writer=writer, graph_reader=reader, idempotency_store=InMemoryIdempotencyStore()
        )
        assert tool.tier is PermissionTier.T3_INTERNAL_WRITE
