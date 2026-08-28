"""Deterministic structural verification for A55 (spec §13.2 Step 6,
§13.6, §15.10, PHASES.md Gate 10) — E2's half of
`backend/app/agents/concierge/`.

**This is Gate 10's single most safety-critical module.** `verify_call_
outcome` is the entire deterministic core of "a booking is not recorded
until verified" (spec §13.2 Step 6) / "unverified outcome never recorded
— proven by test" (Gate 10's own literal checklist item). It takes no
model, makes no Gemini call, and reads no field from a parsed LLM
response — it is a pure comparison of two already-real, already-typed
dataclasses (`types.CallBrief`, the household's real authorised bounds;
`types.CallOutcomeReport`, what the call agent claims happened).

Mirrors this codebase's established "external checkable signal, never
LLM self-critique" split (`app.solvers.fair_allocation.verify_ef1` for
A19's EF1 check is the direct prior-phase precedent) — the only place a
model is ever consulted for A55 is
`confirmation_verifier_agent.ConfirmationVerifierAgent`'s *optional*,
*narrowing-only* semantic cross-check layered on top of this function's
result, never a replacement for it. See that module's docstring for the
full two-layer argument.
"""

from __future__ import annotations

from .types import CallBrief, CallOutcomeReport, VerificationVerdict


def verify_call_outcome(*, brief: CallBrief, report: CallOutcomeReport) -> VerificationVerdict:
    """Cross-checks a claimed call outcome against exactly what the
    original `CallBrief` authorised — spec §13.2 Step 6's "cross-checked
    against what was requested."

    Args:
        brief: the real `CallBrief` this call was authorised under
            (A53's output, or the exact copy handed to E3's A54).
        report: what E3's A54 claims happened.

    Returns:
        A `VerificationVerdict`. `verified=True` only when every one of
        the following holds:
          - `report.disclosure_given` is `True` (checked first, and
            checked alone — spec §23's non-negotiable disclosure
            requirement is never traded off against anything else found
            afterward).
          - `report.out_of_bounds_encountered` is `False` (there is no
            field on `CallOutcomeReport` proving an out-of-bounds
            request was safely resolved, so any `True` here is always
            treated as unresolved — conservative by construction, never
            a guess that it was handled).
          - `report.claimed_slot` is not `None` (a `None` slot means
            nothing was actually booked — there is nothing to verify as
            a *booking*, regardless of anything else; this is the
            legitimate "I'll confirm and call back" case, not a
            discrepancy, but it still never reaches `verified=True`
            because there is no booking to verify).
          - `report.target_provider_id == brief.target_provider_id`.
          - `report.claimed_slot` falls within `brief.date_range`.
          - `report.claimed_slot` is one of `brief.preferred_slots`, OR
            `brief.fallback_acceptable` is `True` (spec §13.2 Step 5:
            "slot gone -> take the next fitting one within pre-
            authorised bounds").

        Any single failure produces `verified=False` with every real,
        specific discrepancy found (not just the first) — never a
        generic "something looks off."
    """
    if not report.disclosure_given:
        return VerificationVerdict(
            verified=False,
            discrepancies=(
                "disclosure_given is False — the automated-assistant disclosure was never confirmed; "
                "this is a hard failure per spec §23 and verification stops here, before any further "
                "check runs",
            ),
            requires_human_callback=True,
        )

    discrepancies: list[str] = []

    if report.target_provider_id != brief.target_provider_id:
        discrepancies.append(
            f"call outcome names provider {report.target_provider_id!r}, but the brief authorised "
            f"only {brief.target_provider_id!r}"
        )

    if report.out_of_bounds_encountered:
        discrepancies.append(
            "out_of_bounds_encountered is True — the call reported an out-of-bounds request, and "
            "CallOutcomeReport carries no field proving it was safely declined or resolved, so this "
            "is never treated as resolved"
        )

    if report.claimed_slot is None:
        discrepancies.append("no slot was claimed booked in this outcome report — there is nothing to record")
        return VerificationVerdict(
            verified=False, discrepancies=tuple(discrepancies), requires_human_callback=True
        )

    start, end = brief.date_range
    if not (start <= report.claimed_slot <= end):
        discrepancies.append(
            f"claimed_slot {report.claimed_slot.isoformat()} falls outside the authorised date_range "
            f"({start.isoformat()} to {end.isoformat()})"
        )

    if report.claimed_slot not in brief.preferred_slots and not brief.fallback_acceptable:
        discrepancies.append(
            f"claimed_slot {report.claimed_slot.isoformat()} is not one of the authorised "
            "preferred_slots, and fallback_acceptable is False for this call"
        )

    if discrepancies:
        return VerificationVerdict(
            verified=False, discrepancies=tuple(discrepancies), requires_human_callback=True
        )

    return VerificationVerdict(verified=True, discrepancies=(), requires_human_callback=False)


__all__ = ["verify_call_outcome"]
