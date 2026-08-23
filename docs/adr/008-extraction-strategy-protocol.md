# ADR-008: `ExtractionStrategy` Protocol for the Document-Type Registry

**Status:** accepted
**Phase:** 3
**Date:** 2026-08-23

## Context

Phase 3 splits ownership: E3 builds the Document-Type Registry (spec §5.4, all 14 types) as a Strategy pattern; E2 builds the agents that extract from documents and route them through it. Nothing froze the actual interface between "the registry" and "a type's edge-mapping logic" before work started, and the two roles run in parallel — without a frozen shape, they'd invent incompatible interfaces independently.

## Decision

Added to `contracts/graph_types.py`: `ExtractedField` (one field's value + per-field confidence/region/derivation), `GraphMappingResult` (the nodes/edges one strategy call produces, plus verification findings and a `registry_gap` flag), and `ExtractionStrategy` (a `Protocol` with one method, `map_to_graph`). `DocumentTypeSpec` gained a `target_edge_types` field (it already had `target_node_types` but was missing the edge side spec §5.4.1 calls for).

The registry (E3) maps `type_id -> (DocumentTypeSpec, ExtractionStrategy)`. The pipeline — A2 routes, A3 extracts using `DocumentTypeSpec.field_schema` (schema-driven, generic across all 14 types), the resolved strategy's `map_to_graph()` turns extracted fields into graph writes, `GraphWriter` applies them — never branches on `type_id` itself. Adding a 15th document type means one new `DocumentTypeSpec` + one new class implementing `ExtractionStrategy`, registered; no pipeline code changes.

Strategies return data (`GraphMappingResult`), never write to Firestore themselves — keeps Layer 3/Layer 5 separation intact (a strategy is reasoning, not action).

## Alternatives considered

1. **Fully declarative edge mapping** (a data-only spec describing field→edge transformations, interpreted by one generic mapper, zero per-type Python code). Rejected: some types genuinely need real logic (line-item receipts iterate a list into many `PURCHASE_ITEM` nodes; verification documents compare against existing graph state) — spec §15.2 already assigns these to dedicated agents (A3b, A3c), acknowledging they're not purely declarative. A rigid mapping DSL good enough for the simple cases and expressive enough for the complex ones would be more machinery, designed under time pressure, for no real gain over well-tested, ordinary classes.
2. **One big per-type `if/elif` in the extraction pipeline.** Rejected outright — exactly what spec §5.4's "the registry is open" design point exists to prevent, and explicitly named as wrong in `gharos-standards`.

## Consequences

E2 and E3 can now build in parallel against a shape neither invented alone. Each of the 14 `ExtractionStrategy` implementations is independently unit-testable (construct `ExtractedField` tuples by hand, assert the `GraphMappingResult`) without needing a real document, a real LLM call, or a real registry lookup.
