import { describe, expect, it } from "vitest";
import {
  createGrowthPacer,
  GRAPH_GROWTH_MAX_LEAD_MS,
  GRAPH_GROWTH_STAGGER_MS,
} from "./graph-growth-pacing";

describe("graph growth pacing (spec §24 graph-growth beat)", () => {
  it("does not delay the first arrival", () => {
    const pacer = createGrowthPacer();
    expect(pacer.schedule(1_000_000)).toBe(1_000_000);
  });

  it("spaces a burst of simultaneous arrivals exactly one stagger apart", () => {
    const pacer = createGrowthPacer();
    const t0 = 1_000_000;
    // Six frames all received in the same millisecond (a batch extraction).
    const revealTimes = [t0, t0, t0, t0, t0, t0].map((t) => pacer.schedule(t));
    expect(revealTimes).toEqual([
      t0,
      t0 + GRAPH_GROWTH_STAGGER_MS,
      t0 + GRAPH_GROWTH_STAGGER_MS * 2,
      t0 + GRAPH_GROWTH_STAGGER_MS * 3,
      t0 + GRAPH_GROWTH_STAGGER_MS * 4,
      t0 + GRAPH_GROWTH_STAGGER_MS * 5,
    ]);
  });

  it("keeps consecutive reveals monotonically increasing and at least a stagger apart", () => {
    const pacer = createGrowthPacer();
    const t0 = 5_000_000;
    // A messy burst: mostly-simultaneous with a little jitter.
    const arrivals = [t0, t0 + 10, t0 + 15, t0 + 20, t0 + 400, t0 + 410];
    const reveals = arrivals.map((t) => pacer.schedule(t));
    for (let i = 1; i < reveals.length; i += 1) {
      expect(reveals[i]).toBeGreaterThanOrEqual(reveals[i - 1] + GRAPH_GROWTH_STAGGER_MS);
    }
  });

  it("adds no artificial delay to genuinely spaced-out arrivals (e.g. the 2:20 voice beat)", () => {
    const pacer = createGrowthPacer();
    // A burst first…
    pacer.schedule(1_000_000);
    pacer.schedule(1_000_000);
    // …then a lone arrival a full minute later: it reveals immediately.
    const lone = 1_000_000 + 60_000;
    expect(pacer.schedule(lone)).toBe(lone);
  });

  it("never pushes a reveal more than the lead cap past its real arrival", () => {
    const pacer = createGrowthPacer();
    const t0 = 2_000_000;
    // A burst far larger than the demo's — 200 frames in one instant.
    let maxLead = 0;
    for (let i = 0; i < 200; i += 1) {
      const revealAt = pacer.schedule(t0);
      maxLead = Math.max(maxLead, revealAt - t0);
    }
    expect(maxLead).toBeLessThanOrEqual(GRAPH_GROWTH_MAX_LEAD_MS);
  });

  it("resumes staggering after a large burst once real time has moved past the lead horizon", () => {
    const pacer = createGrowthPacer();
    const t0 = 3_000_000;
    for (let i = 0; i < 100; i += 1) pacer.schedule(t0);
    // Well past the capped horizon: the next arrival is on real time again…
    const later = t0 + GRAPH_GROWTH_MAX_LEAD_MS + 10_000;
    expect(pacer.schedule(later)).toBe(later);
    // …and a follow-up in the same instant staggers off it as normal.
    expect(pacer.schedule(later)).toBe(later + GRAPH_GROWTH_STAGGER_MS);
  });

  it("honours a custom stagger", () => {
    const pacer = createGrowthPacer(1000);
    const t0 = 42;
    expect(pacer.schedule(t0)).toBe(t0);
    expect(pacer.schedule(t0)).toBe(t0 + 1000);
  });

  it("keeps the stagger constant in lock-step with the --motion-graph-stagger token", () => {
    // The token in styles/tokens.css is authored as `450ms`; this constant
    // mirrors it because canvas draw code cannot read a CSS custom property.
    expect(GRAPH_GROWTH_STAGGER_MS).toBe(450);
  });
});
