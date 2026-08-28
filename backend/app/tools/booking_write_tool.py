"""`BookingWriteTool` — the real T3 graph-write path that closes the
Outbound Concierge loop (spec §13.2 Step 6-7: "a booking is not recorded
until verified" / "close the loop: obligation marked complete; OUTCOME
node written; provider interaction history updated"), PHASES.md Phase 10.

## The verification boundary — this module's whole reason to exist

Gate 10's CTO review is literal: "is there any code path writing a
booking without verification? If yes, the phase fails." This module makes
that unreachable by **type**, not by a runtime `if verified:` check
scattered at call sites:

- `BookingWriteTool.invoke_idempotent` only accepts a real
  `app.agents.concierge.types.VerifiedBooking` instance via its `booking`
  kwarg — anything else (a plain dict, a `CallOutcomeReport`, a
  `VerificationResult` with `verified=False`) raises `ToolFailure` before
  any write is attempted.
- `VerifiedBooking` has no `verified: bool` field to set carelessly. The
  **only** function in this codebase that constructs one is
  `verified_booking_from_verification` below, which itself raises
  `BookingNotVerified` given anything short of a real, positive
  verification with a real confirmed slot. If a `VerifiedBooking`
  instance exists anywhere, verification already happened — the type
  itself is the proof, matching this phase's own instructions
  ("a type signature that requires one, not a boolean flag a caller could
  pass True carelessly").

## Why this takes primitive kwargs, not E2's `VerificationResult`

`verified_booking_from_verification` takes plain, primitive-typed
keyword arguments (`bool`, `str`, `datetime`, ...) rather than importing
E2's A55 `app.agents.concierge.types.VerificationResult` dataclass. This
is a deliberate Phase-10 parallel-dispatch boundary choice, not an
oversight: E2's caller unpacks its own `VerificationResult`'s fields into
this function's keyword arguments (`verified=result.verified,
confirmed_slot=result.confirmed_slot, ...`) — the two roles' code shares
no class import here, only a keyword-argument shape, which is exactly what
`types.VerificationResult`'s own docstring (E2's half of `types.py`)
independently confirms it was designed for: "Deliberately plain/primitive-
shaped... so `app.tools.booking_write_tool.verified_booking_from_
verification`... can pull exactly the fields it needs without importing
this module's full agent-output envelope."

T3 is not a gated tier (`contracts.tools.GATED_TIERS` is T4/T5/T6 only),
so — unlike `app.arbitration.voice_call_tool.VoiceCallTool` — this tool is
registrable from anywhere `PermissionTier.T3_INTERNAL_WRITE` is a writer
agent's permitted tier, matching `app.tools.graph_write_tool.
GraphWriteTool`'s own precedent exactly.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime

from contracts.actions import ActionResult
from contracts.errors import ToolFailure
from contracts.graph_types import (
    AgentId,
    Derivation,
    Edge,
    EdgeId,
    EdgeType,
    NodeId,
    Obligation,
    ObligationStatus,
    Outcome,
    Provenance,
    SourceRef,
)
from contracts.repositories import GraphReader, GraphWriter, IdempotencyStore
from contracts.tools import IdempotentTool, PermissionTier

from app.agents.concierge.types import VerifiedBooking

_TRANSCRIPT_REGION = "whole-transcript"
"""Matches `app.arbitration.voice_call_tool._TRANSCRIPT_REGION` exactly —
the `SourceRef.region` every provenance pointer back to a call transcript
uses in this codebase."""


class BookingNotVerified(Exception):
    """Raised by `verified_booking_from_verification` when the given
    verification signal is anything short of a real, positive
    verification with a real confirmed slot. This is the *only* place in
    this codebase a `VerifiedBooking` could fail to be constructed — see
    module docstring."""

    def __init__(self, *, call_id: str, reason: str) -> None:
        self.call_id = call_id
        self.reason = reason
        super().__init__(f"booking for call '{call_id}' is not verified: {reason}")


def verified_booking_from_verification(
    *,
    verified: bool,
    call_id: str,
    obligation_id: NodeId,
    person_id: NodeId,
    target_provider_id: NodeId,
    transcript_source_document_id: NodeId,
    confirmed_slot: datetime | None,
    confirmed_price: float | None,
    attribution_tags: tuple[str, ...],
    verified_by_agent: AgentId,
    now: datetime | None = None,
) -> VerifiedBooking:
    """The one sanctioned way to construct a `VerifiedBooking`.

    Raises:
        BookingNotVerified: `verified` is `False`, or `confirmed_slot` is
            `None` (a "verified" outcome with nothing confirmed to book
            is a contradiction this function refuses to paper over).
    """
    if not verified:
        raise BookingNotVerified(call_id=call_id, reason="verification reported verified=False")
    if confirmed_slot is None:
        raise BookingNotVerified(call_id=call_id, reason="verified=True but no confirmed_slot was given")
    return VerifiedBooking(
        call_id=call_id,
        obligation_id=obligation_id,
        person_id=person_id,
        target_provider_id=target_provider_id,
        transcript_source_document_id=transcript_source_document_id,
        confirmed_slot=confirmed_slot,
        confirmed_price=confirmed_price,
        attribution_tags=attribution_tags,
        verified_by_agent=verified_by_agent,
        verified_at=now if now is not None else datetime.now(UTC),
    )


class BookingWriteTool(IdempotentTool):
    """T3 — provenance-enforcing (delegates every write to the real
    `GraphWriter`, whose own guard rejects incomplete provenance before
    any write, exactly `GraphWriteTool`'s established precedent) and
    idempotency-keyed."""

    def __init__(
        self,
        *,
        graph_writer: GraphWriter,
        graph_reader: GraphReader,
        idempotency_store: IdempotencyStore,
        name: str = "booking_write_tool",
    ) -> None:
        self.name = name
        self.tier: PermissionTier = PermissionTier.T3_INTERNAL_WRITE
        self._writer = graph_writer
        self._reader = graph_reader
        self._idempotency_store = idempotency_store

    def invoke_idempotent(self, idempotency_key: str, **kwargs: object) -> ActionResult[object]:
        """Args (via kwargs):
            booking: a real `VerifiedBooking` — see module docstring.
                Anything else raises `ToolFailure` before any read/write.

        Returns:
            `ActionResult.success(outcome_node_id)` — the written
            `Outcome` node's id, as a `str`. On replay, the original
            call's result, with no read or write attempted.

        Raises:
            contracts.errors.ToolFailure: `booking` missing/malformed, no
                active `Obligation` exists for `booking.obligation_id`, or
                the underlying `GraphWriter` failed — never a fabricated
                success (safety invariant #7).
        """
        cached_result_ref = self._idempotency_store.check_and_reserve(idempotency_key)
        if cached_result_ref is not None:
            return ActionResult.success(cached_result_ref)

        booking = kwargs.get("booking")
        if not isinstance(booking, VerifiedBooking):
            raise ToolFailure(
                tool_name=self.name,
                reason="'booking' must be a real app.agents.concierge.types.VerifiedBooking instance",
                retryable=False,
            )

        try:
            result_ref = self._perform(booking)
        except ToolFailure:
            raise
        except Exception as exc:  # noqa: BLE001 — tool boundary, matching graph_write_tool.py's identical comment.
            raise ToolFailure(tool_name=self.name, reason=str(exc), retryable=True) from exc

        self._idempotency_store.record_result(idempotency_key, result_ref)
        return ActionResult.success(result_ref)

    def _perform(self, booking: VerifiedBooking) -> str:
        current = self._reader.get_node(booking.obligation_id)
        if not isinstance(current, Obligation):
            raise ToolFailure(
                tool_name=self.name,
                reason=f"no active Obligation found for {booking.obligation_id!r}",
                retryable=False,
            )

        provenance = Provenance(
            derivation=Derivation.EXTRACTED,
            source_ref=SourceRef(
                source_document_id=booking.transcript_source_document_id, region=_TRANSCRIPT_REGION
            ),
            confidence=1.0,
            deriving_agent=booking.verified_by_agent,
            created_at=booking.verified_at,
        )

        price_clause = f" at {booking.confirmed_price:.2f}" if booking.confirmed_price is not None else ""
        actual = (
            f"booked with provider {booking.target_provider_id} for "
            f"{booking.confirmed_slot.isoformat()}{price_clause}"
        )
        outcome = Outcome(
            id=NodeId(f"outcome:{uuid.uuid4().hex}"),
            provenance=provenance,
            predicted=current.title,
            actual=actual,
            variance=None,
            attribution_tags=booking.attribution_tags,
        )
        outcome_id = self._writer.write_node(outcome)

        updated_obligation = replace(current, status=ObligationStatus.COMPLETED, provenance=provenance)
        self._writer.supersede_node(booking.obligation_id, updated_obligation)

        self._writer.write_edge(
            Edge(
                id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                provenance=provenance,
                edge_type=EdgeType.BOOKED_WITH,
                from_id=booking.obligation_id,
                to_id=booking.target_provider_id,
            )
        )
        self._writer.write_edge(
            Edge(
                id=EdgeId(f"edge:{uuid.uuid4().hex}"),
                provenance=provenance,
                edge_type=EdgeType.COMPLETES_INTO,
                from_id=booking.obligation_id,
                to_id=outcome_id,
            )
        )

        return str(outcome_id)


__all__ = ["BookingNotVerified", "BookingWriteTool", "verified_booking_from_verification"]
