"""GharOS — the audit subsystem (Phase 1, E1 lead).

`FirestoreAuditLog` (`audit_log.py`) is the real, durable, append-only
backing for `contracts.repositories.AuditLog` (L6, spec §6.2).
`write_before_execute` and `AuditGuardedAction` (`write_before_execute.py`)
make safety invariant #2 ("audit before execute") structural: an `Action`
cannot reach `execute()` with a `None` `audit_ref` when built through this
package's sanctioned path.
"""

from __future__ import annotations
