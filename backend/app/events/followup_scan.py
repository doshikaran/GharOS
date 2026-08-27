"""A31 — Follow-up / Persistence (spec §10.3.E, §15.roster, PHASES.md
Phase 7).

*Responsibility:* "Track open claims and vendor requests; re-contact on
cadence; escalate after N." *Model tier:* Flash. *Note (spec, verbatim):*
"where autonomous persistence beats humans most decisively."

This module is the deterministic decision core only: given a batch of open
items, decide which are stale enough to need another contact attempt and
which have exhausted their attempts and need a human — no model call at
all, in the same sense `app.agents.consequence.obligation_writer` (A15) is
nominally "Flash tier" in the roster but is, in its own docstring's words,
"plain deterministic code": staleness is arithmetic over timestamps and
counts, not judgment. `followup_dispatcher.py` (same package) turns a
`FollowUpDecision` into a real effect (a published Pub/Sub event, or a real
`EscalationAgent.route()` call).

## The A30 `RecoveryDraft` interface this module assumes — flag for the CTO

A30 Recovery Drafting is E2's Phase-7 deliverable, dispatched in parallel
with this module and not guaranteed to exist yet at the time this was
written. Rather than block on it, `FollowUpTrackable` below is the minimal
shape this module actually needs from *any* open, trackable item — a real
`RecoveryDraft`, once it lands, needs to satisfy this Protocol (structurally
— no inheritance required) for A31 to track it. **This is an assumption to
reconcile against E2's real type, not a frozen contract** — if A30's
`RecoveryDraft` ends up shaped differently, this Protocol (and nothing
downstream of it needs to change) is what to adjust.

The same Protocol also covers A33 Vendor Relations' "plumber who said
'tomorrow' four days ago" vendor-request case (`vendor_id` is populated,
`claim_id` is not) — one scanner, two callers, per this module's own
"track open claims *and* vendor requests" responsibility line.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Protocol


class FollowUpItemStatus(StrEnum):
    """Whatever produced the trackable item's own lifecycle status —
    only `OPEN` items are ever scanned; anything else is filtered out
    before staleness is even considered (a resolved claim re-contacting
    the vendor would be a real, visible bug, not a missed edge case)."""

    OPEN = "open"
    RESOLVED = "resolved"
    ABANDONED = "abandoned"


class FollowUpTrackable(Protocol):
    """Minimal shape A31 needs from an open claim / recovery draft /
    vendor request. Structural (`Protocol`) — a real `RecoveryDraft` (A30,
    E2) or a vendor-request record (A33, this same phase, `app.adapters.
    vendor_relations`) needs no inheritance from this, only these
    attributes.

    Declared as read-only `@property` getters, deliberately, rather than
    plain attribute annotations: mypy's structural Protocol matching
    treats a plain annotation as requiring a *settable* attribute on the
    implementer, which every `frozen=True` node/dataclass in this
    codebase (per `contracts.graph_types`' own universal convention — and
    almost certainly A30's real `RecoveryDraft`, following that same
    convention) never has. A read-only Protocol is satisfiable by both a
    frozen dataclass and a mutable one; a settable-attribute Protocol
    would reject every frozen dataclass in this codebase outright.
    """

    @property
    def id(self) -> str: ...
    @property
    def created_at(self) -> datetime: ...
    @property
    def last_contact_attempt_at(self) -> datetime | None:
        """`None` if no follow-up contact has been attempted yet —
        staleness is then measured from `created_at` itself."""
        ...

    @property
    def attempt_count(self) -> int:
        """How many re-contact attempts have already been made."""
        ...

    @property
    def vendor_id(self) -> str | None:
        """Populated for a vendor-request-shaped item; `None` for a claim/
        dispute-shaped item with no single vendor counterparty."""
        ...

    @property
    def status(self) -> FollowUpItemStatus: ...
    @property
    def involves_financial(self) -> bool:
        """Whether an escalation for this item should be routed to a
        financially-capable household member (`EscalationContext.
        involves_financial`, `app.arbitration.escalation_agent`) — `True`
        for a recovery draft chasing money, `False` for a purely
        scheduling-shaped vendor request (e.g. "the plumber never called
        back")."""
        ...


FollowUpAction = Literal["recontact", "escalate", "skip"]


@dataclass(frozen=True, slots=True)
class FollowUpDecision:
    """One trackable item's disposition for this scan pass."""

    item_id: str
    action: FollowUpAction
    reason: str
    attempt_count: int
    """The attempt count this decision was made *against* — for
    `"recontact"`, the dispatcher increments past this; for `"escalate"`,
    this is the count that crossed `max_attempts`."""
    vendor_id: str | None
    involves_financial: bool


@dataclass(frozen=True, slots=True)
class FollowUpScanConfig:
    recontact_cadence: timedelta = timedelta(days=3)
    """How long since the last contact attempt (or, if none yet, since
    `created_at`) before an open item is stale enough to re-contact."""
    max_attempts: int = 3
    """Attempts beyond this are never re-tried automatically — spec's own
    "escalate after N" (§15 roster A31) becomes real here: the (N+1)-th
    stale check on the same item escalates instead of re-contacting."""


class FollowUpScanner:
    """A31's pure decision core — no I/O, no model call, dependency-free
    by design so `followup_dispatcher.py` (and, separately,
    `app.events.followup_scan` itself) can be unit-tested with plain
    Python objects, no emulator required."""

    def __init__(self, *, config: FollowUpScanConfig | None = None) -> None:
        self._config = config or FollowUpScanConfig()

    def scan(self, *, items: tuple[FollowUpTrackable, ...], now: datetime) -> tuple[FollowUpDecision, ...]:
        """Decides one `FollowUpDecision` per item in `items`.

        `RESOLVED`/`ABANDONED` items are skipped without being scored at
        all (never re-contacted, never escalated) — closed items have no
        business appearing in this scan's output as anything but absent.
        """
        decisions: list[FollowUpDecision] = []
        for item in items:
            if item.status is not FollowUpItemStatus.OPEN:
                continue
            since_reference = item.last_contact_attempt_at or item.created_at
            elapsed = now - since_reference
            if elapsed < self._config.recontact_cadence:
                decisions.append(
                    FollowUpDecision(
                        item_id=item.id,
                        action="skip",
                        reason=(
                            f"last contact {elapsed} ago, within the "
                            f"{self._config.recontact_cadence} cadence — not yet due"
                        ),
                        attempt_count=item.attempt_count,
                        vendor_id=item.vendor_id,
                        involves_financial=item.involves_financial,
                    )
                )
                continue

            if item.attempt_count >= self._config.max_attempts:
                decisions.append(
                    FollowUpDecision(
                        item_id=item.id,
                        action="escalate",
                        reason=(
                            f"{item.attempt_count} contact attempt(s) already made, at or beyond the "
                            f"{self._config.max_attempts}-attempt ceiling — a human decides next, not "
                            "another automated attempt"
                        ),
                        attempt_count=item.attempt_count,
                        vendor_id=item.vendor_id,
                        involves_financial=item.involves_financial,
                    )
                )
                continue

            decisions.append(
                FollowUpDecision(
                    item_id=item.id,
                    action="recontact",
                    reason=(
                        f"stale for {elapsed} (cadence {self._config.recontact_cadence}), "
                        f"attempt {item.attempt_count + 1} of {self._config.max_attempts}"
                    ),
                    attempt_count=item.attempt_count,
                    vendor_id=item.vendor_id,
                    involves_financial=item.involves_financial,
                )
            )
        return tuple(decisions)


__all__ = [
    "FollowUpAction",
    "FollowUpDecision",
    "FollowUpItemStatus",
    "FollowUpScanConfig",
    "FollowUpScanner",
    "FollowUpTrackable",
]
