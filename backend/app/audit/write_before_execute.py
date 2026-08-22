"""Safety invariant #2 — "every autonomous action writes an audit record
*before* it executes" — made structural, not a documentation promise.

Two pieces work together:

1. `AuditGuardedAction` — an optional base class future `Action`
   implementations (`backend/app/tools/`, E3, Phase 5+) can inherit from.
   Its `execute()` refuses to run (`AuditNotWritten`) unless `audit_ref`
   is populated; subclasses implement `_perform()` instead of `execute()`
   directly, so they cannot accidentally bypass the guard by overriding
   `execute()` and forgetting the check.
2. `write_before_execute` — the one sanctioned entry point for actually
   running an `Action`. It writes the audit record to a real `AuditLog`
   *first*, builds the `AuditRef` from that durably-written record, then
   calls a caller-supplied factory to construct the `Action` — meaning the
   `Action` object cannot come into being with a populated `audit_ref`
   without the audit record already existing.

Together these make "construct an `Action` with a real `audit_ref` without
first writing the audit record" and "call `execute()` on an `Action` with
no `audit_ref`" both structurally unreachable through this module's API,
rather than something callers are trusted to get right.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from datetime import UTC, datetime
from typing import TypeVar

from contracts.actions import Action, ActionResult, AuditRef
from contracts.repositories import AuditLog

from app.audit.errors import AuditNotWritten

ResultT = TypeVar("ResultT")


class AuditGuardedAction(Action[ResultT], ABC):
    """Base class for concrete `Action` implementations that want "audit
    before execute" enforced structurally rather than by convention.

    Subclasses implement `_perform()` (the actual effect) instead of
    `execute()`. `execute()` itself is final in spirit — it is not marked
    `@final` (contracts/actions.py is frozen and does not import
    `typing.final` machinery for this), but overriding it defeats the
    entire purpose of inheriting from this class, so it is written to make
    that obviously wrong at the call site: the guard runs before anything
    else, unconditionally.
    """

    def execute(self) -> ActionResult[ResultT]:
        if self.audit_ref is None:
            raise AuditNotWritten(action_type=type(self).__name__)
        return self._perform()

    @abstractmethod
    def _perform(self) -> ActionResult[ResultT]:
        """The actual effect. Only ever reached once `execute()` has
        confirmed `audit_ref` is populated."""
        raise NotImplementedError


def write_before_execute[ResultT](
    audit_log: AuditLog,
    *,
    action_type: str,
    payload: dict[str, str],
    occurred_at: datetime,
    build_action: Callable[[AuditRef], Action[ResultT]],
) -> ActionResult[ResultT]:
    """Writes an audit record durably, then builds and executes an
    `Action` from it — in that order, unconditionally.

    Args:
        audit_log: the real `AuditLog` (`FirestoreAuditLog` in Phase 1+).
        action_type: what kind of action this is (audit record field).
        payload: audit record payload — the evidence for *why* this action
            is about to run.
        occurred_at: when the triggering event happened (may predate
            "now" — e.g. a receipt's transaction time).
        build_action: constructs the `Action` to run, given the `AuditRef`
            for the record just written. This is the only way this
            function hands a caller an `AuditRef` — there is no path that
            skips the `audit_log.append` call above it.

    Returns:
        The `Action`'s `ActionResult` from `execute()`.
    """
    audit_record_id = audit_log.append(action_type=action_type, payload=payload, occurred_at=occurred_at)
    audit_ref = AuditRef(audit_record_id=audit_record_id, written_at=datetime.now(UTC))
    action = build_action(audit_ref)
    return action.execute()


__all__ = ["AuditGuardedAction", "AuditNotWritten", "write_before_execute"]
