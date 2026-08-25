/**
 * TypeScript mirror of the Phase 6 graph wire contracts (PHASES.md Phase 6,
 * E4 work item — the graph visualisation).
 *
 * Source of truth, read directly rather than guessed at:
 *   - `backend/app/graph/serialization.py`'s module docstring — the
 *     canonical node/edge JSON envelope shape and the frozen
 *     `NODE_TYPE_TAGS` node-type string convention (16 literal strings,
 *     upper-snake-case of the `contracts.graph_types` class name).
 *   - `backend/app/api/graph_router.py` — `NodeEnvelope` / `EdgeEnvelope` /
 *     `GraphSnapshotResponse` / `JustificationResponse` Pydantic models,
 *     mirrored field-for-field (snake_case wire keys kept as-is here,
 *     matching this codebase's existing convention of not camelCasing
 *     fetched JSON in `lib/graph-api.ts` — the interfaces below are typed
 *     directly against the real response body).
 *
 * These contracts are owned exclusively by the CTO / E1 (`contracts/`,
 * `backend/app/api/`). This file mirrors their shape; it never redefines it.
 */

// ---------------------------------------------------------------------------
// Node-type tags — `app.graph.serialization.NODE_TYPE_TAGS`, frozen wire
// convention. One literal per entry, spelled out (not derived) so the exact
// wire string stays grep-able here too.
// ---------------------------------------------------------------------------

export const NODE_TYPES = [
  "PERSON",
  "CONSTRAINT",
  "OBLIGATION",
  "LEDGER_EVENT",
  "RECURRING_COMMITMENT",
  "VENDOR",
  "PROVIDER",
  "DECISION",
  "BRANCH",
  "COUNCIL_POSITION",
  "OUTCOME",
  "SOURCE_DOCUMENT",
  "ACTION_RECORD",
  "APPROVAL_REQUEST",
  "PURCHASE_ITEM",
  "PATTERN",
] as const;

export type NodeType = (typeof NODE_TYPES)[number];

// ---------------------------------------------------------------------------
// Derivation — `contracts.graph_types.Derivation`, mirrors
// `DerivationBadge`'s `DerivationTag` exactly.
// ---------------------------------------------------------------------------

export type Derivation = "extracted" | "inferred" | "ambiguous";

export const DERIVATIONS: readonly Derivation[] = ["extracted", "inferred", "ambiguous"];

// ---------------------------------------------------------------------------
// Node / edge envelopes — `app.api.graph_router.NodeEnvelope` / `EdgeEnvelope`
// ---------------------------------------------------------------------------

export interface GraphNode {
  readonly id: string;
  readonly type: NodeType;
  readonly label: string;
  readonly derivation: Derivation | null;
  /** 0.0-1.0. */
  readonly confidence: number | null;
  readonly source_document_id: string | null;
  /** Region-locator string — see `lib/region-locator.ts` for the two
   * conventions this can hold. `null` alongside `source_document_id` when
   * there is no single source (legitimate for AMBIGUOUS derivation). */
  readonly region: string | null;
  /** ISO 8601, or `null` — mirrors `Provenance.created_at` once JSON-safe. */
  readonly created_at: string | null;
  /** Every per-node-type field this node's codec wrote, untouched. */
  readonly fields: Readonly<Record<string, unknown>>;
}

export interface GraphEdge {
  readonly id: string;
  /** `contracts.graph_types.EdgeType.value` — already lower-snake, e.g. "implies". */
  readonly type: string;
  readonly from_id: string;
  readonly to_id: string;
  readonly derivation: Derivation | null;
  readonly confidence: number | null;
  readonly is_conflict: boolean;
}

export interface GraphSnapshot {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
}

// ---------------------------------------------------------------------------
// Justification — `app.api.graph_router.JustificationResponse`
// ---------------------------------------------------------------------------

export interface JustificationEdgeSummary {
  readonly id: string;
  readonly type: string;
  readonly from_id: string;
  readonly to_id: string;
}

export interface JustificationStep {
  readonly node_id: string;
  readonly depth: number;
  /** `null` only for the root/depth-0 step. */
  readonly via_edge: JustificationEdgeSummary | null;
}

export interface JustificationSourceDocument {
  readonly id: string;
  readonly channel: string;
  readonly region: string | null;
}

export interface JustificationResponse {
  readonly root_node_id: string;
  readonly steps: readonly JustificationStep[];
  readonly source_documents: readonly JustificationSourceDocument[];
}

// ---------------------------------------------------------------------------
// Person-association edges — CTO-frozen scope boundary for the Person filter
// dimension (Phase 6 brief): a node is "associated with" a PERSON if it IS
// that PERSON node, or is connected to it by an edge of one of these five
// types, in either direction.
// ---------------------------------------------------------------------------

export const PERSON_ASSOCIATION_EDGE_TYPES: readonly string[] = [
  "owned_by",
  "benefits",
  "constrains",
  "approved_by",
  "conceded_by",
];
