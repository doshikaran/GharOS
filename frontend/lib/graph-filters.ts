/**
 * Client-side graph filtering (Phase 6 CTO scope boundary — filters run
 * entirely against the node/edge set already loaded from `/graph/snapshot`
 * plus whatever has streamed in since; there is no backend filter query
 * this phase).
 *
 * Four dimensions, exact semantics per the frozen brief:
 *   - **Type**: multi-select over the 16 `NodeType` values.
 *   - **Person**: a node is "associated with" a person if it IS that
 *     PERSON node, or is connected to it by a `PERSON_ASSOCIATION_EDGE_TYPES`
 *     edge, either direction.
 *   - **Time window**: filters on every node's `created_at`.
 *   - **Derivation**: extracted/inferred/ambiguous, multi-select.
 *
 * Filtering is node-first: when a node is filtered out, every edge
 * touching it disappears too — an edge to an invisible node is never shown
 * dangling.
 */

import { PERSON_ASSOCIATION_EDGE_TYPES, type Derivation, type GraphEdge, type GraphNode, type NodeType } from "./graph-types";

export interface TimeWindow {
  /** ISO 8601, inclusive. `null` means unbounded on this side. */
  readonly from: string | null;
  readonly to: string | null;
}

export interface GraphFilterState {
  /** `null` means "no type filter" (show every type) — an empty array
   * would instead mean "show nothing", which is a real, selectable state
   * distinct from "filter not engaged yet". */
  readonly types: readonly NodeType[] | null;
  /** `null` means "no person filter". A PERSON node id. */
  readonly personId: string | null;
  readonly timeWindow: TimeWindow | null;
  readonly derivations: readonly Derivation[] | null;
}

export const EMPTY_GRAPH_FILTER_STATE: GraphFilterState = {
  types: null,
  personId: null,
  timeWindow: null,
  derivations: null,
};

function matchesType(node: GraphNode, filters: GraphFilterState): boolean {
  if (filters.types === null) return true;
  return filters.types.includes(node.type);
}

function matchesDerivation(node: GraphNode, filters: GraphFilterState): boolean {
  if (filters.derivations === null) return true;
  return node.derivation !== null && filters.derivations.includes(node.derivation);
}

function matchesTimeWindow(node: GraphNode, filters: GraphFilterState): boolean {
  if (filters.timeWindow === null) return true;
  if (node.created_at === null) return false;
  const createdAt = new Date(node.created_at).getTime();
  const { from, to } = filters.timeWindow;
  if (from !== null && createdAt < new Date(from).getTime()) return false;
  if (to !== null && createdAt > new Date(to).getTime()) return false;
  return true;
}

/** Builds the set of node ids associated with `personId`: the PERSON node
 * itself, plus every node connected to it by a `PERSON_ASSOCIATION_EDGE_TYPES`
 * edge, either direction. */
function buildPersonAssociatedIds(personId: string, edges: readonly GraphEdge[]): ReadonlySet<string> {
  const associated = new Set<string>([personId]);
  for (const edge of edges) {
    if (!PERSON_ASSOCIATION_EDGE_TYPES.includes(edge.type)) continue;
    if (edge.from_id === personId) associated.add(edge.to_id);
    if (edge.to_id === personId) associated.add(edge.from_id);
  }
  return associated;
}

export interface FilteredGraph {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
}

/**
 * Applies `filters` to `nodes`/`edges`, node-first: a node survives only if
 * it passes every engaged dimension, then edges survive only if both
 * endpoints survived.
 */
export function applyGraphFilters(
  nodes: readonly GraphNode[],
  edges: readonly GraphEdge[],
  filters: GraphFilterState,
): FilteredGraph {
  const personAssociatedIds =
    filters.personId !== null ? buildPersonAssociatedIds(filters.personId, edges) : null;

  const visibleNodes = nodes.filter((node) => {
    if (!matchesType(node, filters)) return false;
    if (!matchesDerivation(node, filters)) return false;
    if (!matchesTimeWindow(node, filters)) return false;
    if (personAssociatedIds !== null && !personAssociatedIds.has(node.id)) return false;
    return true;
  });

  const visibleIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = edges.filter((edge) => visibleIds.has(edge.from_id) && visibleIds.has(edge.to_id));

  return { nodes: visibleNodes, edges: visibleEdges };
}

/** True if any filter dimension is currently engaged (used to drive an
 * "N of M nodes shown" summary / a "clear filters" affordance). */
export function hasActiveFilters(filters: GraphFilterState): boolean {
  return (
    filters.types !== null ||
    filters.personId !== null ||
    filters.timeWindow !== null ||
    filters.derivations !== null
  );
}
