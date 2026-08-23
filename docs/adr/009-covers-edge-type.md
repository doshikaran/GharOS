# ADR-009: Add the `covers` edge type (OBLIGATION → PURCHASE_ITEM)

**Status:** accepted
**Phase:** 3
**Date:** 2026-08-23

## Context

Spec §5.4.2's WARRANTY / PURCHASE PROTECTION entry states its edges explicitly: "links back to the originating RECEIPT's PURCHASE_ITEM — this is why receipt line-item extraction matters months later." E3, building the Phase 3 document-type registry, found `contracts.graph_types.EdgeType`'s frozen enum has no edge type connecting an OBLIGATION (the warranty claim-or-lose obligation) to a PURCHASE_ITEM at all. Every other named edge relationship in spec §5.4.2 maps onto an existing `EdgeType` member; this one genuinely doesn't.

## Decision

Added `EdgeType.COVERS` (`OBLIGATION → PURCHASE_ITEM`): the warranty obligation covers/protects the specific purchased item. `document_type_specs.py`'s `warranty` entry's `target_edge_types` updated to include it (mechanical, one-line follow-up to this contract addition).

## Alternatives considered

1. **Repurpose an existing edge type** (e.g. `DISCHARGES`, which is `PURCHASE_ITEM | LEDGER_EVENT → OBLIGATION` — the reverse direction and a different meaning: "this purchase settled that obligation," not "this obligation protects that purchase"). Rejected: reusing an edge type for a meaning it wasn't designed for defeats the entire point of typed, directional edges — a query for `discharges` edges would then return both "purchases that paid off a debt" and "warranties tracking a purchase," which is exactly the kind of ambiguity the graph model exists to prevent.
2. **Leave it unencoded**, as E3's registry did pending this decision (`warranty`'s `target_edge_types` was `(STATES,)` only). Rejected as a lasting state: this is not a speculative future need like DEBT-002 (ACTION_RECORD/APPROVAL_REQUEST, which needs real Phase 5 usage patterns to design well) — spec §5.4.2 already fully specifies both the relationship and its purpose. There's nothing to learn by waiting.

## Consequences

`EdgeType` has 30 members (was 29 after ADR-005 removed `argued_by`). `gharos-graph-model` skill and `.claude/agents/e1.md` updated to reflect the new count. E2's Phase 3 warranty `ExtractionStrategy` (next) writes a real `covers` edge from the warranty OBLIGATION to the PURCHASE_ITEM identified in the originating receipt — the mechanism spec §5.4.2 calls "why receipt line-item extraction matters months later" now has an edge to actually walk.
