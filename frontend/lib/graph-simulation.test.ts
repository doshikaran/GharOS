import { afterEach, describe, expect, it, vi } from "vitest";
import {
  createGraphSimulation,
  isSimulationActive,
  reheatSimulation,
  stepSimulation,
  type SimLink,
  type SimNode,
} from "./graph-simulation";

function buildSyntheticGraph(nodeCount: number, edgeCount: number): { nodes: SimNode[]; links: SimLink[] } {
  const nodes: SimNode[] = Array.from({ length: nodeCount }, (_, i) => ({ id: `n${i}` }));
  const links: SimLink[] = Array.from({ length: edgeCount }, (_, i) => ({
    id: `e${i}`,
    // A mix of local and long-range connections, roughly like a real
    // household graph (mostly-local structure with some cross-links).
    source: `n${i % nodeCount}`,
    target: `n${(i * 7 + 1) % nodeCount}`,
  }));
  return { nodes, links };
}

describe("graph simulation at demo scale (500+ nodes)", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("stops its own internal timer, ticking only ever happens via an explicit stepSimulation call", () => {
    vi.useFakeTimers();
    const { nodes, links } = buildSyntheticGraph(20, 15);
    const sim = createGraphSimulation(nodes, links, { width: 800, height: 600 });
    const alphaAfterCreate = sim.alpha();

    // Plenty of time for d3-timer's own rAF/setTimeout-driven loop to have
    // run many ticks on its own if createGraphSimulation had NOT called
    // .stop() — alpha must stay exactly where creation left it.
    vi.advanceTimersByTime(5000);

    expect(sim.alpha()).toBe(alphaAfterCreate);
  });

  it(
    "measures real wall-clock cost of stepping a 500-node/700-edge simulation " +
      "to convergence, an honest, repo-runnable performance signal for the demo-scale claim " +
      "(not an architectural assertion): logs the measured duration for the record.",
    () => {
      const NODE_COUNT = 500;
      const EDGE_COUNT = 700;
      const { nodes, links } = buildSyntheticGraph(NODE_COUNT, EDGE_COUNT);
      const sim = createGraphSimulation(nodes, links, { width: 1200, height: 800 });

      const startedAt = performance.now();
      let ticks = 0;
      // Mirrors GraphCanvas's own draw-loop stepping condition.
      while (isSimulationActive(sim) && ticks < 1000) {
        stepSimulation(sim);
        ticks += 1;
      }
      const elapsedMs = performance.now() - startedAt;

      console.log(
        `[graph-simulation perf] ${NODE_COUNT} nodes / ${EDGE_COUNT} edges settled in ${ticks} ticks, ` +
          `${elapsedMs.toFixed(1)}ms wall-clock (${(elapsedMs / ticks).toFixed(3)}ms/tick).`,
      );

      // The simulation must actually settle (not run away to the 1000-tick
      // cap) and every position must stay finite — a diverging layout would
      // be a real correctness bug, not just a performance concern.
      expect(isSimulationActive(sim)).toBe(false);
      for (const node of nodes) {
        expect(Number.isFinite(node.x)).toBe(true);
        expect(Number.isFinite(node.y)).toBe(true);
      }

      // A generous ceiling — this is Node's plain JS engine with no JIT
      // warmup tricks, no GPU, no browser compositor; the real per-frame
      // budget in a browser draw loop is far smaller than this total. This
      // assertion exists to catch a genuine algorithmic regression (e.g.
      // an accidental O(n^2) blowup), not to certify 60fps in a browser.
      expect(elapsedMs).toBeLessThan(5000);
    },
  );

  it("reheating after new nodes/edges arrive resumes stepping without a full reset", () => {
    const { nodes, links } = buildSyntheticGraph(50, 40);
    const sim = createGraphSimulation(nodes, links, { width: 800, height: 600 });
    while (isSimulationActive(sim)) stepSimulation(sim);
    expect(isSimulationActive(sim)).toBe(false);

    reheatSimulation(sim);
    expect(isSimulationActive(sim)).toBe(true);
  });
});
