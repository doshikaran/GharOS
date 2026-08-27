"""Deterministic, non-LLM solvers (spec §16.2): Phase 4 conflict pre-pass,
Phase 7 salary arithmetic, Phase 8 fairness (MNW/EF1+PO), Phase 11
calibration/variance, Phase 12 council mechanism arbiter.

Phase 4 adds the first solver proper: `app.solvers.conflict_prepass`
(`DeterministicConflictPrepass`) — spec §7.3 Stage 3's temporal, resource,
capability, and load conflict checks, run before A14 (Conflict Radar,
E2) spends a Pro-tier reasoning call.

Phase 7 adds `app.solvers.salary_calculator` (`calculate_salary`) — spec
§16.2's "days − absences − advances" arithmetic, run by A34 (Staff
Payroll, E2) after it has interpreted a handwritten register into a real
`AttendanceRecord` (ADR-013, DEBT-004's repayment). Real advance amounts
are sourced from `LedgerEvent` nodes of `kind=LedgerEventKind.ADVANCE`,
never from `AttendanceRecord.advance_notations`.

Phase 1's two deterministic-tool line items from this same spec section —
the idempotency key generator and the graph integrity checker — are
implemented elsewhere because they are graph/persistence primitives, not
standalone solvers with their own algorithm: idempotency key generation is
`contracts.actions.IdempotencyKey.as_str()` (frozen contract) backed by
`app.persistence.idempotency_store.FirestoreIdempotencyStore`; the graph
integrity checker is `app.graph.integrity_checker.FirestoreGraphIntegrityChecker`
(it needs the same node/edge access `FirestoreGraphReader` has, so it lives
beside it). Both are deterministic and non-LLM, consistent with this
package's charter — this docstring exists so a future reader searching
`app/solvers/` for either one finds a pointer instead of nothing.
"""

from __future__ import annotations
