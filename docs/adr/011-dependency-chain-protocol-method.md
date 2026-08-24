# ADR-011: Promote `dependency_chain` to the `GraphReader` Protocol

**Status:** accepted
**Phase:** 4
**Date:** 2026-08-24

## Context

Spec §7.3 Stage 4 requires "must-start-by computed backwards through dependencies" — walking an OBLIGATION's `depends_on` chain. `neighbours()` (the existing Protocol traversal) is deliberately bidirectional and cannot alone distinguish "obligations this one depends on" from "obligations that depend on this one." E1 built a working concrete implementation (`FirestoreGraphReader.dependency_chain`) but correctly did not add it to the frozen `contracts.repositories.GraphReader` Protocol themselves (contracts are CTO-only) — reported it back instead. E2's A15 Obligation Writer, which builds must-start-by computation this same phase, is typed against the Protocol, not the concrete class, and cannot reach a concrete-only method.

## Decision

Added `dependency_chain(obligation_id: NodeId, *, max_depth: int = 25) -> tuple[Obligation, ...]` to `contracts.repositories.GraphReader`, matching E1's already-working concrete signature exactly. No new abstraction invented — this promotes a proven implementation to the contract, rather than designing a new one speculatively.

## Alternatives considered

- **Leave it concrete-only, have E2 import `FirestoreGraphReader` directly.** Rejected: breaks the Repository pattern's entire point (PHASES.md §2.2) — every reasoning agent depends on the `GraphReader` Protocol, never a concrete Firestore type, so tests can inject a fake without a real emulator. A concrete-only escape hatch here would be the first crack in that discipline.

## Consequences

Any `GraphReader` implementation (the real Firestore-backed one, any future test double) must now implement `dependency_chain`. `mypy --strict` confirms the existing `FirestoreGraphReader` already satisfies it structurally — no code change needed there, just the Protocol catching up to what already existed.
