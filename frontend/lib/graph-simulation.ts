/**
 * d3-force simulation factory for the graph canvas — the only place this
 * module touches `d3` (already the installed dependency; PHASES.md Phase 6
 * requires an ADR only if switching D3 -> Cytoscape, which this codebase
 * does not do).
 *
 * Deliberately framework/DOM-agnostic (no canvas, no React) so it can be
 * driven from `GraphCanvas`'s draw loop *and* exercised directly in a
 * plain unit test that measures its own performance at 500+-node demo
 * scale without needing a real browser canvas (`graph-simulation.test.ts`).
 *
 * The simulation's own internal timer is stopped immediately after
 * creation (`sim.stop()`) — the caller drives ticking explicitly via
 * `stepSimulation`, once per animation frame, so growth-animation timing
 * and simulation physics share one clock instead of racing two independent
 * `requestAnimationFrame` loops.
 */

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  type Simulation,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3";

export interface SimNode extends SimulationNodeDatum {
  id: string;
}

export interface SimLink extends SimulationLinkDatum<SimNode> {
  id: string;
}

export type GraphSimulation = Simulation<SimNode, SimLink>;

export interface SimulationOptions {
  width: number;
  height: number;
  /** Node radius used for collision spacing — a single representative
   * value is enough for collision force purposes even though drawn radii
   * vary slightly by type. */
  nodeRadius?: number;
}

const DEFAULT_NODE_RADIUS = 14;

/**
 * Builds a stopped `d3-force` simulation over `nodes`/`links` — charge
 * (mutual repulsion), link (edges pull connected nodes together), centring,
 * and collision (keeps nodes from overlapping). Positions already present
 * on `nodes` (e.g. a node persisted from a previous render) are preserved;
 * new nodes start unpositioned and d3 seeds them via its default (a
 * deterministic phyllotaxis layout), which then relaxes via the sim.
 */
export function createGraphSimulation(nodes: SimNode[], links: SimLink[], options: SimulationOptions): GraphSimulation {
  const nodeRadius = options.nodeRadius ?? DEFAULT_NODE_RADIUS;
  const sim = forceSimulation<SimNode>(nodes)
    .force("charge", forceManyBody().strength(-90))
    .force(
      "link",
      forceLink<SimNode, SimLink>(links)
        .id((node) => node.id)
        .distance(60)
        .strength(0.3),
    )
    .force("center", forceCenter(options.width / 2, options.height / 2))
    .force("collide", forceCollide(nodeRadius * 1.4))
    .alphaDecay(0.02)
    .stop();
  return sim;
}

/** Advances the simulation by exactly one tick — call once per animation
 * frame from the caller's own draw loop. */
export function stepSimulation(sim: GraphSimulation): void {
  sim.tick();
}

/** True while the simulation still has meaningful energy left (worth
 * continuing to step); false once it has settled below `alphaMin`. Lets
 * the caller stop stepping (and stop scheduling animation frames purely
 * for physics) once the layout has visually stabilised. */
export function isSimulationActive(sim: GraphSimulation): boolean {
  return sim.alpha() > sim.alphaMin();
}

/** Reheats a stopped/settled simulation slightly — used when new nodes or
 * edges arrive live, so the layout visibly resettles around them rather
 * than the newcomer landing frozen at its seed position. */
export function reheatSimulation(sim: GraphSimulation, alphaTarget: number = 0.4): void {
  sim.alpha(alphaTarget);
}
