# ADR-005: Remove the `argued_by` edge type

**Status:** accepted
**Phase:** 1
**Date:** 2026-08-22

## Context

While building the Phase 1 graph integrity checker, E1 found that `EdgeType.ARGUED_BY` (`COUNCIL_POSITION → AGENT`, spec §5.3) can never be a valid graph edge: `AGENT` is not one of the 16 node types (spec §5.2) — agents are identified throughout the system by the string `AgentId` (`contracts.graph_types.AgentId`), never by a graph node. `Edge.to_id` is typed as `NodeId`, so an `argued_by` edge would either point at a `NodeId` that doesn't resolve to any real node (a permanent dangling edge) or require inventing an AGENT node type solely to be an edge target, which spec §5.2's node list does not include and nothing else in the system needs.

Separately, `contracts.graph_types.CouncilPosition` already carries `held_by_agent: AgentId` as a direct field on the node — the information `argued_by` would encode already exists, just not as a graph edge.

## Decision

Remove `ARGUED_BY` from `contracts.graph_types.EdgeType`. `CouncilPosition.held_by_agent` remains the single source of truth for which agent holds a given position — this is not a loss of information, it's removing a second, unusable way of expressing information the node shape already carries directly.

## Alternatives considered

1. **Add an AGENT node type** so `argued_by` has a valid target. Rejected: nothing else in the system needs agents to be graph nodes (they are computational roles, not household entities — conflating them with PERSON or introducing a third identity concept adds real complexity for zero benefit; `held_by_agent: AgentId` already does the job).
2. **Leave `ARGUED_BY` in the enum, unused.** Rejected: an edge type in a frozen contract that no code can ever legally construct is exactly the kind of latent inconsistency a careful reviewer (or a judge reading the architecture) would flag — better to remove it now, at Phase 1, before the Council (Phase 12) is built around it, than to carry known-dead surface forward.

## Consequences

- `contracts/graph_types.py`'s `EdgeType` enum now has 29 members instead of 30 (spec §5.3's table lists `supports`/`opposes` as a single combined row, but they are two distinct enum members — so the true pre-removal count was 30, not the 29 the spec table's row-count suggests). Every reference to "29 edge types" in the spec, PHASES.md, and this repo's own skills/docs was counting table rows, not enum members, and is now understood as historical — the `gharos-graph-model` skill is updated to reflect 29 actual members and note the removal.
- No code changes needed anywhere else: `ARGUED_BY` was never used in Phase 0 or Phase 1 (E1 confirmed this in their Phase 1 report), so removing it has zero downstream impact on seed data, tests, or the integrity checker.
- Phase 12 (Council) implementation should use `CouncilPosition.held_by_agent` directly rather than looking for an `argued_by` edge that no longer exists in the contract.
