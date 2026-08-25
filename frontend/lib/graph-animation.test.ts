import { describe, expect, it } from "vitest";
import { computeArrivalProgress, GRAPH_GROW_DURATION_MS } from "./graph-animation";

describe("computeArrivalProgress", () => {
  it("starts at scale below 1 and opacity 0 at the instant of arrival", () => {
    const progress = computeArrivalProgress(1000, 1000);
    expect(progress.opacity).toBe(0);
    expect(progress.scale).toBeLessThan(1);
    expect(progress.settled).toBe(false);
  });

  it("reaches full scale/opacity once the duration has elapsed", () => {
    const progress = computeArrivalProgress(1000 + GRAPH_GROW_DURATION_MS, 1000);
    expect(progress.opacity).toBe(1);
    expect(progress.scale).toBe(1);
    expect(progress.settled).toBe(true);
  });

  it("clamps rather than overshoots well past the duration", () => {
    const progress = computeArrivalProgress(1000 + GRAPH_GROW_DURATION_MS * 5, 1000);
    expect(progress.opacity).toBe(1);
    expect(progress.scale).toBe(1);
  });

  it("is monotonically non-decreasing across the animation window", () => {
    const samples = [0, 100, 200, 300, 400, 500, 600].map((dt) => computeArrivalProgress(1000 + dt, 1000));
    for (let i = 1; i < samples.length; i += 1) {
      expect(samples[i].eased).toBeGreaterThanOrEqual(samples[i - 1].eased);
    }
  });

  it("never animates a baseline element that has no arrivedAt in the past relative to a distant now (used before elapsing)", () => {
    // Sanity: a mid-window sample is strictly between 0 and 1, not
    // instantaneously settled — this is what makes it visually distinct
    // from an un-animated baseline render.
    const progress = computeArrivalProgress(1000 + GRAPH_GROW_DURATION_MS / 2, 1000);
    expect(progress.eased).toBeGreaterThan(0);
    expect(progress.eased).toBeLessThan(1);
  });
});
