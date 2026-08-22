"""Audit-package-local error types.

Not `contracts/errors.py` — that module is CTO-owned and frozen, and
safety invariant #2 ("audit before execute") is enforced entirely within
`backend/app/audit/`, so its failure mode does not need a
cross-cutting typed exception in the shared contract module. Any future
phase that *does* need to catch this from outside `app.audit` should raise
that need to the CTO rather than have E1 add it to `contracts/errors.py`
unilaterally.
"""

from __future__ import annotations


class AuditNotWritten(RuntimeError):
    """Raised when an `Action` reaches `execute()` (via `AuditGuardedAction`)
    without a populated `audit_ref`. This is safety invariant #2 made
    structural: the only sanctioned way to obtain a populated `audit_ref`
    is `write_before_execute`, which durably writes the audit record
    first."""

    def __init__(self, *, action_type: str) -> None:
        self.action_type = action_type
        super().__init__(f"cannot execute '{action_type}': audit_ref is None (invariant #2)")
