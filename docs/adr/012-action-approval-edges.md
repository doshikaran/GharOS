# ADR-012: Add `acts_on`, `authorizes`, and `approved_by` edge types (ACTION_RECORD / APPROVAL_REQUEST)

**Status:** accepted
**Phase:** 5
**Date:** 2026-08-24

## Context

DEBT-002 (opened Phase 1) recorded that ACTION_RECORD and APPROVAL_REQUEST — two of the 16 node types — have no `EdgeType` member able to name them as an endpoint, so E1's Phase 1 graph integrity checker has special-cased both out of orphan detection since Phase 1 rather than either producing permanent false-positive noise or inventing an edge type without a real consumer in view. Phase 5 (Arbitration, Approval & Action Layer) is the first phase where real code actually produces ACTION_RECORD and APPROVAL_REQUEST nodes (the Confidence Arbiter, Approval Gate, and tool layer built this phase) — DEBT-002's own repayment condition named this exact phase as the right place to design these edges against actual usage.

Spec §5.2 describes ACTION_RECORD as "what the system did, when, under whose approval." The existing frozen shape (`action_type: str`, `executed_at: datetime`, `approved_by: NodeId | None`) covers "when" fully and "under whose approval" partially (a person id, but not the specific ApprovalRequest that authorized it) — but has no field or edge naming *what* the action acted on at all. That is a second, previously-unrecorded gap discovered while designing this ADR, not just DEBT-002's original two missing edges.

## Decision

Three new `EdgeType` members, all added this phase:

1. **`ACTS_ON`** (`ACTION_RECORD → {OBLIGATION | LEDGER_EVENT | VENDOR | PROVIDER | RECURRING_COMMITMENT}`) — the "what" half of ACTION_RECORD's description. Every action that isn't purely internal must point at the real node it affected.
2. **`AUTHORIZES`** (`APPROVAL_REQUEST → ACTION_RECORD`) — the specific approval request that authorized a specific executed action, at request granularity, not just person granularity.
3. **`APPROVED_BY`** (`APPROVAL_REQUEST → PERSON`) — the graph-traversal-visible form of who approved a request, kept *alongside* `ActionRecord.approved_by`'s existing scalar field rather than replacing it.

`EdgeType` now has 33 members (was 30 after ADR-009).

## Alternatives considered

1. **Remove `ActionRecord.approved_by` and rely solely on the new `APPROVED_BY` edge**, to keep every relationship edge-first with no scalar duplication (the convention every other node in this graph follows — e.g. `Obligation` has no `owner_id` scalar, only an `OWNED_BY` edge). Rejected: `approved_by` is an already-relied-upon field referenced directly in the frozen `ActionRecord` dataclass docstring since Phase 0, and removing it now is a breaking change to a frozen Phase-0 contract for a purely stylistic gain — the edge and the scalar field answer different questions cheaply (`APPROVED_BY` answers "every approval Priya has granted," the scalar answers "who approved this one action" without a graph read) and are not in tension with each other.
2. **A single `AFFECTS` edge type covering ACTS_ON, AUTHORIZES, and APPROVED_BY's three distinct meanings.** Rejected for the same reason ADR-009 rejected reusing `DISCHARGES` for `COVERS`: collapsing three semantically distinct relationships into one untyped edge defeats the purpose of typed, directional edges and would make a query for e.g. "every action taken on this obligation" return approvals and approvers mixed in with actions.
3. **Leave `ACTS_ON` for a later phase**, since DEBT-002 only named two edges. Rejected: an ACTION_RECORD with no edge to what it acted on is not meaningfully auditable — spec §5.2's own description of the node requires this, and Phase 5 is precisely the phase that starts producing real ACTION_RECORD nodes, so waiting would mean shipping the exact "declared a shape nothing produces or nothing consumes correctly" gap this project has corrected twice before (Phase 3's `utility_bill`/`insurance_document` edge-type mismatches).

## Consequences

`backend/app/graph/integrity_checker.py`'s ACTION_RECORD/APPROVAL_REQUEST special-case is removed this phase (E1) now that both node types have real edges to be reachable by. E3's Approval Gate and Confidence Arbiter (this phase) write all three edge types as part of every real approval → action flow — never as a follow-up. `gharos-graph-model` skill and `.claude/agents/e1.md` updated to reflect the new 33-edge count. DEBT-002 is struck this phase; see `docs/DEBT.md`.
