"""Safety invariant #2 — "audit before execute" — proven against the
real, Firestore-emulator-backed `FirestoreAuditLog` and the real
`write_before_execute` / `AuditGuardedAction` helpers (upgrading Phase
0's stub-based `test_safety_invariants.py` proof, per the E1 charter).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from contracts.actions import ActionResult, AuditRef, IdempotencyKey, RiskTier

from app.audit.audit_log import FirestoreAuditLog
from app.audit.errors import AuditNotWritten
from app.audit.write_before_execute import AuditGuardedAction, write_before_execute


@dataclass(frozen=True, slots=True)
class _SendNotificationAction(AuditGuardedAction[str]):
    """A minimal concrete `Action` built on `AuditGuardedAction` — stands
    in for a future `backend/app/tools/` (E3, Phase 5+) implementation.
    Never overrides `execute()` — only `_perform()`, so the audit-before
    guard in the base class cannot be bypassed by this subclass."""

    risk_tier: RiskTier
    idempotency_key: IdempotencyKey
    audit_ref: AuditRef | None
    message: str
    side_effect_log: list[str]

    def _perform(self) -> ActionResult[str]:
        self.side_effect_log.append(self.message)
        return ActionResult.success(self.message)


class TestFirestoreAuditLogReadPaths:
    def test_get_returns_none_for_unknown_record(self, audit_log: FirestoreAuditLog) -> None:
        assert audit_log.get("does-not-exist") is None

    def test_all_records_reflects_every_appended_record(self, audit_log: FirestoreAuditLog) -> None:
        assert audit_log.all_records() == ()
        id_1 = audit_log.append(action_type="a", payload={"k": "v1"}, occurred_at=datetime.now(UTC))
        id_2 = audit_log.append(action_type="b", payload={"k": "v2"}, occurred_at=datetime.now(UTC))
        records = {r.id: r for r in audit_log.all_records()}
        assert set(records) == {id_1, id_2}
        assert records[id_1].action_type == "a"
        assert records[id_2].payload == {"k": "v2"}


class TestAuditGuardedActionRefusesWithoutAuditRef:
    def test_execute_without_audit_ref_raises(self) -> None:
        side_effects: list[str] = []
        action = _SendNotificationAction(
            risk_tier=RiskTier.R1_NOTIFY,
            idempotency_key=IdempotencyKey(entity_id="e1", action_type="notify", cycle="2026-08"),
            audit_ref=None,
            message="should never run",
            side_effect_log=side_effects,
        )
        with pytest.raises(AuditNotWritten):
            action.execute()
        assert side_effects == []  # the effect never ran

    def test_execute_with_populated_audit_ref_succeeds(self) -> None:
        side_effects: list[str] = []
        action = _SendNotificationAction(
            risk_tier=RiskTier.R1_NOTIFY,
            idempotency_key=IdempotencyKey(entity_id="e1", action_type="notify", cycle="2026-08"),
            audit_ref=AuditRef(audit_record_id="fake-but-populated", written_at=datetime.now(UTC)),
            message="hello",
            side_effect_log=side_effects,
        )
        result = action.execute()
        assert result.ok is True
        assert result.value == "hello"
        assert side_effects == ["hello"]


class TestWriteBeforeExecute:
    def test_audit_record_exists_before_the_action_effect_runs(self, audit_log: FirestoreAuditLog) -> None:
        side_effects: list[str] = []
        observed_audit_ref: list[AuditRef] = []

        def build_action(audit_ref: AuditRef) -> _SendNotificationAction:
            # at the moment this factory runs, the audit record must
            # already be durably readable — proves ordering, not just
            # that a ref object exists in memory.
            record = audit_log.get(audit_ref.audit_record_id)
            assert record is not None
            observed_audit_ref.append(audit_ref)
            return _SendNotificationAction(
                risk_tier=RiskTier.R1_NOTIFY,
                idempotency_key=IdempotencyKey(entity_id="e2", action_type="notify", cycle="2026-08"),
                audit_ref=audit_ref,
                message="audited hello",
                side_effect_log=side_effects,
            )

        result = write_before_execute(
            audit_log,
            action_type="notify",
            payload={"summary": "test action"},
            occurred_at=datetime.now(UTC),
            build_action=build_action,
        )

        assert result.ok is True
        assert result.value == "audited hello"
        assert side_effects == ["audited hello"]
        assert len(observed_audit_ref) == 1

        # the audit record is durably readable after the fact too
        record = audit_log.get(observed_audit_ref[0].audit_record_id)
        assert record is not None
        assert record.action_type == "notify"
        assert record.payload == {"summary": "test action"}

    def test_no_sanctioned_path_skips_the_audit_write(self, audit_log: FirestoreAuditLog) -> None:
        """There is no way to call `write_before_execute` and reach
        `build_action` without `audit_log.append` having already run —
        the audit_ref handed to the factory is only ever constructed from
        the id `append` returned."""
        calls: list[str] = []

        class _RecordingAuditLog(FirestoreAuditLog):
            def append(self, *, action_type: str, payload: dict[str, str], occurred_at: datetime) -> str:
                calls.append("append")
                return super().append(action_type=action_type, payload=payload, occurred_at=occurred_at)

        recording_log = _RecordingAuditLog(audit_log._client)  # noqa: SLF001

        def build_action(audit_ref: AuditRef) -> _SendNotificationAction:
            assert calls == ["append"]  # append already happened by the time we get here
            return _SendNotificationAction(
                risk_tier=RiskTier.R0_SILENT,
                idempotency_key=IdempotencyKey(entity_id="e3", action_type="notify", cycle="2026-08"),
                audit_ref=audit_ref,
                message="ok",
                side_effect_log=[],
            )

        write_before_execute(
            recording_log,
            action_type="notify",
            payload={},
            occurred_at=datetime.now(UTC),
            build_action=build_action,
        )
        assert calls == ["append"]
