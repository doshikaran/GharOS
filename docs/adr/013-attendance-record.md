# ADR-013: Add the `AttendanceRecord` node type and `attendance_of` edge type

**Status:** accepted
**Phase:** 7
**Date:** 2026-08-25

## Context

DEBT-004 (opened Phase 3) recorded that `contracts.graph_types.Person` has no field or related node type for per-day staff presence marks, so Phase 3's `attendance_register` `ExtractionStrategy` writes zero graph nodes for a successfully-extracted register — the extracted marks are summarized into `GraphMappingResult.verification_findings` (text) only, nothing durable or queryable. DEBT-004's own repayment condition named Phase 7 (A34 Staff Payroll Agent, the real consumer of this data) as the right place to design the shape, rather than guessing in Phase 3 ahead of a real consumption pattern.

Phase 7's A34 (spec §15.9/§10.3: "attendance -> days worked -> minus advances -> salary due") is that real consumer. Spec's own formula names three real inputs: attendance (per-day presence), advances (already representable as `LedgerEvent` nodes with `LedgerEventKind.ADVANCE`), and the arithmetic itself (a deterministic solver, per spec §16.2 — never LLM arithmetic).

## Decision

Added `AttendanceRecord` (one node per staff member per calendar month, not per day — `app.solvers.salary_calculator`'s whole formula operates on one pay cycle at a time, and a per-day node would mean 28-31 graph reads to answer the one question this system ever asks of this data) with: `staff_person_id`, `month` (`"YYYY-MM"`), rollup counts (`days_present`, `days_absent`, `days_on_leave`, `total_days_in_period`), a `daily_marks` dict (day-of-month -> mark) keeping the real per-day record auditable alongside the rollup, and `advance_notations` (raw margin text, cross-reference only — never authoritative; real advance amounts come from real `LedgerEvent` nodes, never parsed back out of handwritten annotations).

Added `EdgeType.ATTENDANCE_OF` (`ATTENDANCE_RECORD -> PERSON`), the staff member the record belongs to.

`Phase 3`'s `attendance_register` `ExtractionStrategy` is updated this phase to actually write both, replacing its `verification_findings`-only behaviour.

## Alternatives considered

1. **One node per day** (`AttendanceDayMark`, 28-31 per staff member per month). Rejected: real consumption is always "give me this person's month" (the salary calculator's actual query shape), never "give me this person's Tuesday" — a per-day node adds real write/read volume for a granularity nothing in this system queries at.
2. **A field on `Person` instead of a separate node type** (e.g. `Person.attendance: dict[str, ...]`). Rejected on the same grounds every other per-period/per-event fact in this graph is its own node rather than a growing field on `Person` (`Constraint`, `Obligation`, `LedgerEvent` are all separate node types, not `Person` fields) — an unbounded, ever-growing dict on the one node every other part of the system reads for identity/capability lookups is exactly the shape drift `contracts/graph_types.py`'s existing design avoids everywhere else.
3. **Fold advance amounts into `AttendanceRecord` directly** (parsing margin notations into a structured amount). Rejected: `LedgerEventKind.ADVANCE` already exists and is the graph's authoritative source for real money movement — duplicating that fact from handwritten margin text into a second node risks the two ever disagreeing about how much was actually advanced. `advance_notations` stays raw text, explicitly documented as cross-reference only.

## Consequences

`contracts.graph_types` now has 17 node types (was 16) and `EdgeType` now has 34 members (was 33 after ADR-012). E1 wires the new type into `app.persistence.collections.NODE_TYPE_TO_COLLECTION`, a new codec in `app.persistence.codecs.nodes`, and `app.graph.serialization.NODE_TYPE_TAGS`/`node_label` (Phase 6's graph-visualisation label dispatch — an `AttendanceRecord` reaching that dispatcher with no entry would raise `ValueError`, so this wiring is not optional follow-up, it is required for the Phase 6 graph view to keep working once real attendance data exists). E1 also builds `app.solvers.salary_calculator`, the deterministic "days present - absences - advances -> salary due" tool A34 calls — arithmetic never happens inside the LLM call, per spec's own explicit rule. `document_type_specs.py`'s `attendance_register` entry (`app/adapters/`, E3-owned) is updated in this same contract-freeze pass, mirroring ADR-009's precedent, since the change is a mechanical, one-entry follow-up to this exact addition: `target_node_types` gains `"ATTENDANCE_RECORD"`, `target_edge_types` gains `EdgeType.ATTENDANCE_OF`. `gharos-graph-model` skill and `.claude/agents/e1.md` updated to reflect the new 17-node/34-edge counts. **DEBT-004 is substantially repaid but not struck this phase** — the node/edge shape, its persistence wiring, and A34's consumption of it are all real and verified; what remains is a production write-path from a freshly-extracted register to a real, graph-written `AttendanceRecord`, which surfaced during this phase's own gate review as one instance of a broader, pre-existing gap (no phase has yet built a genuine end-to-end raw-document-to-graph orchestrator for any node type — see DEBT-009). See `docs/DEBT.md`'s DEBT-004 and DEBT-009 entries for the full, honest accounting.
