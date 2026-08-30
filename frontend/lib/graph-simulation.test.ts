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

      // A deliberately generous ceiling. This is Node's plain JS engine
      // with no JIT warmup tricks, no GPU, no browser compositor; the real
      // per-frame budget in a browser draw loop is far smaller than this
      // total. It runs as one of ~120 test files under a parallel
      // (`forks`) pool, so on a busy CI box the same work that settles in
      // ~1s in isolation is routinely 5-6x slower purely from CPU
      // contention — a wall-clock assertion here has to absorb that or it
      // flakes. The number that still matters is the tick count (asserted
      // via `isSimulationActive` above: it must settle well under the
      // 1000-tick cap); this ceiling only exists to catch a genuine
      // algorithmic regression — an accidental O(n^2) force calc without
      // Barnes-Hut pruning would be ~2 orders of magnitude slower per
      // tick, i.e. minutes, not seconds — never to certify 60fps.
      expect(elapsedMs).toBeLessThan(20000);
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
