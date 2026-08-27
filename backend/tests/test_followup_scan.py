"""Tests for `app.events.followup_scan.FollowUpScanner` (A31) — pure
deterministic staleness/escalation decisions, no I/O, no model call.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.events.followup_scan import (
    FollowUpItemStatus,
    FollowUpScanConfig,
    FollowUpScanner,
)

NOW = datetime(2026, 8, 22, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class _Item:
    """A minimal concrete stand-in structurally satisfying
    `FollowUpTrackable` — exercises the Protocol against a plain dataclass,
    matching how a real `RecoveryDraft` (A30) or vendor-request record
    (A33) would satisfy it with no inheritance."""

    id: str
    created_at: datetime
    last_contact_attempt_at: datetime | None
    attempt_count: int
    vendor_id: str | None
    status: FollowUpItemStatus
    involves_financial: bool = True


def _config(*, cadence_days: int = 3, max_attempts: int = 3) -> FollowUpScanConfig:
    return FollowUpScanConfig(recontact_cadence=timedelta(days=cadence_days), max_attempts=max_attempts)


class TestSkipsNotYetStaleItems:
    def test_item_contacted_recently_is_skipped(self) -> None:
        item = _Item(
            id="item-1",
            created_at=NOW - timedelta(days=10),
            last_contact_attempt_at=NOW - timedelta(hours=1),
            attempt_count=1,
            vendor_id="vendor-1",
            status=FollowUpItemStatus.OPEN,
        )
        scanner = FollowUpScanner(config=_config())
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions[0].action == "skip"


class TestRecontactsStaleItems:
    def test_stale_item_under_attempt_ceiling_is_recontacted(self) -> None:
        item = _Item(
            id="item-2",
            created_at=NOW - timedelta(days=10),
            last_contact_attempt_at=NOW - timedelta(days=4),
            attempt_count=1,
            vendor_id="vendor-2",
            status=FollowUpItemStatus.OPEN,
        )
        scanner = FollowUpScanner(config=_config())
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions[0].action == "recontact"
        assert decisions[0].attempt_count == 1

    def test_staleness_measured_from_created_at_when_never_contacted(self) -> None:
        item = _Item(
            id="item-3",
            created_at=NOW - timedelta(days=5),
            last_contact_attempt_at=None,
            attempt_count=0,
            vendor_id=None,
            status=FollowUpItemStatus.OPEN,
        )
        scanner = FollowUpScanner(config=_config())
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions[0].action == "recontact"


class TestEscalatesAfterNAttempts:
    def test_item_at_attempt_ceiling_is_escalated_not_recontacted(self) -> None:
        item = _Item(
            id="item-4",
            created_at=NOW - timedelta(days=20),
            last_contact_attempt_at=NOW - timedelta(days=5),
            attempt_count=3,
            vendor_id="vendor-4",
            status=FollowUpItemStatus.OPEN,
        )
        scanner = FollowUpScanner(config=_config(max_attempts=3))
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions[0].action == "escalate"

    def test_item_below_ceiling_is_still_recontacted(self) -> None:
        item = _Item(
            id="item-5",
            created_at=NOW - timedelta(days=20),
            last_contact_attempt_at=NOW - timedelta(days=5),
            attempt_count=2,
            vendor_id="vendor-5",
            status=FollowUpItemStatus.OPEN,
        )
        scanner = FollowUpScanner(config=_config(max_attempts=3))
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions[0].action == "recontact"


class TestClosedItemsAreNeverScored:
    def test_resolved_item_produces_no_decision(self) -> None:
        item = _Item(
            id="item-6",
            created_at=NOW - timedelta(days=20),
            last_contact_attempt_at=NOW - timedelta(days=10),
            attempt_count=5,
            vendor_id="vendor-6",
            status=FollowUpItemStatus.RESOLVED,
        )
        scanner = FollowUpScanner(config=_config())
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions == ()

    def test_abandoned_item_produces_no_decision(self) -> None:
        item = _Item(
            id="item-7",
            created_at=NOW - timedelta(days=20),
            last_contact_attempt_at=None,
            attempt_count=5,
            vendor_id=None,
            status=FollowUpItemStatus.ABANDONED,
        )
        scanner = FollowUpScanner(config=_config())
        decisions = scanner.scan(items=(item,), now=NOW)
        assert decisions == ()


class TestBatchScanAccountsForEveryOpenItem:
    def test_mixed_batch_produces_one_decision_per_open_item(self) -> None:
        items = (
            _Item(
                id="skip-me",
                created_at=NOW - timedelta(days=1),
                last_contact_attempt_at=NOW - timedelta(hours=2),
                attempt_count=0,
                vendor_id=None,
                status=FollowUpItemStatus.OPEN,
            ),
            _Item(
                id="recontact-me",
                created_at=NOW - timedelta(days=10),
                last_contact_attempt_at=NOW - timedelta(days=4),
                attempt_count=1,
                vendor_id="vendor-x",
                status=FollowUpItemStatus.OPEN,
            ),
            _Item(
                id="escalate-me",
                created_at=NOW - timedelta(days=20),
                last_contact_attempt_at=NOW - timedelta(days=4),
                attempt_count=3,
                vendor_id="vendor-y",
                status=FollowUpItemStatus.OPEN,
            ),
            _Item(
                id="closed-item",
                created_at=NOW - timedelta(days=20),
                last_contact_attempt_at=None,
                attempt_count=9,
                vendor_id=None,
                status=FollowUpItemStatus.RESOLVED,
            ),
        )
        scanner = FollowUpScanner(config=_config())
        decisions = scanner.scan(items=items, now=NOW)
        by_id = {d.item_id: d.action for d in decisions}
        assert by_id == {"skip-me": "skip", "recontact-me": "recontact", "escalate-me": "escalate"}
