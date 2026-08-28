"""Tests for `app.agents.concierge.verification` — A55's deterministic
structural core.

**This is Gate 10's single most safety-critical test file.** Every test
here constructs plain dataclasses directly — no Gemini mocking at all,
because `verify_call_outcome` makes no model call — and asserts
`verified` is `True` only when every real bound genuinely holds.
"""

from __future__ import annotations

from datetime import UTC, datetime

from contracts.graph_types import NodeId

from app.agents.concierge.types import CallBrief, CallOutcomeReport
from app.agents.concierge.verification import verify_call_outcome

_DATE_RANGE = (datetime(2026, 9, 1, tzinfo=UTC), datetime(2026, 9, 10, tzinfo=UTC))
_PREFERRED_SLOTS = (datetime(2026, 9, 3, 16, 0, tzinfo=UTC), datetime(2026, 9, 4, 10, 0, tzinfo=UTC))


def _brief(*, fallback_acceptable: bool = True) -> CallBrief:
    return CallBrief(
        target_provider_id=NodeId("provider-1"),
        person_id=NodeId("person-aarav"),
        objective="Book a routine dental cleaning for Aarav",
        date_range=_DATE_RANGE,
        price_ceiling=1500.0,
        disclosable_facts=("patient name: Aarav",),
        must_not_answer=("medical diagnosis",),
        preferred_slots=_PREFERRED_SLOTS,
        fallback_acceptable=fallback_acceptable,
    )


def _report(
    *,
    target_provider_id: NodeId | None = None,
    disclosure_given: bool = True,
    claimed_slot: datetime | None = _PREFERRED_SLOTS[0],
    claimed_outcome_summary: str = "Booked the requested slot.",
    out_of_bounds_encountered: bool = False,
    requires_human_callback: bool = False,
) -> CallOutcomeReport:
    return CallOutcomeReport(
        call_id="call-1",
        target_provider_id=target_provider_id if target_provider_id is not None else NodeId("provider-1"),
        transcript_source_document_id=NodeId("doc-transcript-1"),
        disclosure_given=disclosure_given,
        claimed_slot=claimed_slot,
        claimed_outcome_summary=claimed_outcome_summary,
        out_of_bounds_encountered=out_of_bounds_encountered,
        requires_human_callback=requires_human_callback,
    )


class TestGenuineMatch:
    def test_exact_preferred_slot_verifies(self) -> None:
        verdict = verify_call_outcome(brief=_brief(), report=_report(claimed_slot=_PREFERRED_SLOTS[0]))

        assert verdict.verified is True
        assert verdict.discrepancies == ()
        assert verdict.requires_human_callback is False

    def test_fallback_slot_within_bounds_verifies_when_fallback_acceptable(self) -> None:
        fallback_slot = datetime(2026, 9, 7, 11, 0, tzinfo=UTC)
        assert fallback_slot not in _PREFERRED_SLOTS

        verdict = verify_call_outcome(
            brief=_brief(fallback_acceptable=True), report=_report(claimed_slot=fallback_slot)
        )

        assert verdict.verified is True


class TestDisclosureHardFailure:
    """spec §23 / this agent's own contract: disclosure_given=False is a
    hard failure that stops verification before anything else runs."""

    def test_no_disclosure_never_verifies_even_with_everything_else_correct(self) -> None:
        verdict = verify_call_outcome(
            brief=_brief(), report=_report(disclosure_given=False, claimed_slot=_PREFERRED_SLOTS[0])
        )

        assert verdict.verified is False
        assert verdict.requires_human_callback is True
        assert "disclosure_given" in verdict.discrepancies[0]


class TestWrongDate:
    def test_slot_outside_date_range_never_verifies(self) -> None:
        out_of_range_slot = datetime(2026, 10, 1, tzinfo=UTC)

        verdict = verify_call_outcome(brief=_brief(), report=_report(claimed_slot=out_of_range_slot))

        assert verdict.verified is False
        assert any("date_range" in d for d in verdict.discrepancies)

    def test_non_preferred_slot_rejected_when_fallback_not_acceptable(self) -> None:
        non_preferred_but_in_range = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)

        verdict = verify_call_outcome(
            brief=_brief(fallback_acceptable=False), report=_report(claimed_slot=non_preferred_but_in_range)
        )

        assert verdict.verified is False
        assert any("preferred_slots" in d for d in verdict.discrepancies)


class TestWrongProvider:
    def test_provider_mismatch_never_verifies(self) -> None:
        verdict = verify_call_outcome(
            brief=_brief(), report=_report(target_provider_id=NodeId("provider-different"))
        )

        assert verdict.verified is False
        assert any("provider" in d for d in verdict.discrepancies)


class TestOutOfBoundsNeverResolved:
    def test_out_of_bounds_encountered_always_fails_even_with_a_valid_slot(self) -> None:
        verdict = verify_call_outcome(
            brief=_brief(), report=_report(out_of_bounds_encountered=True, claimed_slot=_PREFERRED_SLOTS[0])
        )

        assert verdict.verified is False
        assert verdict.requires_human_callback is True
        assert any("out_of_bounds" in d for d in verdict.discrepancies)


class TestNoSlotClaimed:
    def test_none_slot_never_verifies_but_is_not_a_discrepancy_pile_up(self) -> None:
        """The legitimate 'I'll confirm and call back' case: nothing was
        booked, so there is nothing to verify as a booking — never a
        pass, always requires callback."""
        verdict = verify_call_outcome(
            brief=_brief(), report=_report(claimed_slot=None, requires_human_callback=True)
        )

        assert verdict.verified is False
        assert verdict.requires_human_callback is True


class TestMultipleDiscrepanciesAllReported:
    def test_every_real_discrepancy_is_listed_not_just_the_first(self) -> None:
        verdict = verify_call_outcome(
            brief=_brief(fallback_acceptable=False),
            report=_report(
                target_provider_id=NodeId("provider-different"),
                claimed_slot=datetime(2026, 10, 1, tzinfo=UTC),
            ),
        )

        assert verdict.verified is False
        assert len(verdict.discrepancies) >= 2
