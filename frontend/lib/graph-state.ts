/**
 * Framework-agnostic graph state bookkeeping shared by `GraphExplorer` and
 * its tests. Owns exactly one distinction that matters for Phase 6's
 * "the one place motion carries meaning" requirement: a node/edge that
 * arrived via `/graph/snapshot` (the baseline load) never animates; a
 * node/edge that arrived via `subscribeToGraphStream` (a live mutation)
 * always does, because it is — by `/graph/stream`'s own contract — a
 * genuinely new arrival, never a replay.
 *
 * Deliberately has no React/DOM/canvas dependency, so both a plain unit
 * test and a component-level integration test can exercise the same
 * arrival semantics.
 */

import type { GraphEdge, GraphNode } from "./graph-types";
import type { GraphStreamEvent } from "./graph-stream";

export interface GraphState {
  readonly nodesById: ReadonlyMap<string, GraphNode>;
  readonly edgesById: ReadonlyMap<string, GraphEdge>;
  /** id -> epoch ms at which the id's growth animation should begin.
   * Never populated by `applySnapshot` — only by `applyStreamEvent`. An
   * id present here is what the growth animation keys off of. Normally
   * this is the moment the live frame arrived, but the caller may pass a
   * paced (near-future) timestamp so a burst of arrivals reveals as a
   * legible cadence rather than all at once — see
   * `lib/graph-growth-pacing.ts`. `computeArrivalProgress` treats a
   * still-future value as "not started yet" (opacity 0, min scale). */
  readonly liveArrivedAt: ReadonlyMap<string, number>;
}

export function createEmptyGraphState(): GraphState {
  return { nodesById: new Map(), edgesById: new Map(), liveArrivedAt: new Map() };
}

/** Loads `/graph/snapshot`'s result as the baseline — replaces the node/edge
 * maps wholesale, but never touches `liveArrivedAt`: a snapshot node was
 * already there, and must never be flagged for the growth animation even if
 * (edge case) it shares an id with something the stream already delivered
 * before the snapshot fetch resolved. */
export function applySnapshot(
  state: GraphState,
  snapshot: { readonly nodes: readonly GraphNode[]; readonly edges: readonly GraphEdge[] },
): GraphState {
  const nodesById = new Map(snapshot.nodes.map((node) => [node.id, node] as const));
  const edgesById = new Map(snapshot.edges.map((edge) => [edge.id, edge] as const));
  return { nodesById, edgesById, liveArrivedAt: state.liveArrivedAt };
}

/** Applies one `/graph/stream` frame: upserts the node/edge and stamps its
 * id in `liveArrivedAt` with `now` — every stream frame is a genuinely new
 * arrival per the endpoint's own contract, so this always (re-)triggers
 * the growth animation for that id, even on an update to an id the
 * snapshot already carried. `now` is the timestamp the animation should
 * treat as the arrival: pass raw `Date.now()` for an immediate reveal, or
 * a paced future time (see `lib/graph-growth-pacing.ts`) to stagger a
 * burst. */
export function applyStreamEvent(state: GraphState, event: GraphStreamEvent, now: number = Date.now()): GraphState {
  const liveArrivedAt = new Map(state.liveArrivedAt);
  if (event.kind === "node") {
    const nodesById = new Map(state.nodesById);
    nodesById.set(event.node.id, event.node);
    liveArrivedAt.set(event.node.id, now);
    return { nodesById, edgesById: state.edgesById, liveArrivedAt };
  }
  const edgesById = new Map(state.edgesById);
  edgesById.set(event.edge.id, event.edge);
  liveArrivedAt.set(event.edge.id, now);
  return { nodesById: state.nodesById, edgesById, liveArrivedAt };
}

export function listNodes(state: GraphState): GraphNode[] {
  return [...state.nodesById.values()];
}

export function listEdges(state: GraphState): GraphEdge[] {
  return [...state.edgesById.values()];
}

/** True if `id` arrived via the live stream and is still within
 * `durationMs` of that arrival — i.e. still mid-growth-animation. */
export function isLiveArrival(state: GraphState, id: string, durationMs: number, now: number = Date.now()): boolean {
  const arrivedAt = state.liveArrivedAt.get(id);
  if (arrivedAt === undefined) return false;
  return now - arrivedAt < durationMs;
}
