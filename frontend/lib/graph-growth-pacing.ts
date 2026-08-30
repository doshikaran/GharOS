/**
 * Reveal-pacing for the graph's live growth animation (spec §24, the
 * "0:40-1:40 — autonomous execution + the graph assembling itself" beat).
 *
 * The backend writes the extracted/implied nodes and their provenance
 * edges to Firestore as each one lands, and `GET /graph/stream` forwards
 * every write the instant it happens. For a single batch extraction that
 * is effectively a burst — a dozen-plus frames inside a second or two.
 * Played back verbatim, the graph "pops" into existence in one frame:
 * technically live, but unreadable on camera, and indistinguishable from
 * a pre-seeded render to a judge watching for exactly that.
 *
 * This module spaces the *reveal* of consecutive live arrivals by a fixed
 * stagger so a burst unfolds as a legible cadence — one node, an edge,
 * another node — while never adding artificial delay to genuinely
 * spaced-out arrivals (e.g. the single node the 2:20 voice beat adds).
 * It is pure and stateless-per-instance so it is trivially unit-testable
 * and carries no React/DOM dependency.
 *
 * How it plugs in: `GraphExplorer` calls `pacer.schedule(Date.now())` for
 * each `/graph/stream` frame and passes the returned timestamp as the
 * `now` argument to `applyStreamEvent`, so it is that *paced* time that
 * gets stamped into `GraphState.liveArrivedAt` and drives
 * `computeArrivalProgress` on the canvas. A paced timestamp in the near
 * future simply renders the element at opacity 0 / min scale until its
 * slot arrives (`computeArrivalProgress` clamps a negative elapsed to 0),
 * which is exactly the staggered fade-in we want.
 */

/**
 * Minimum wall-clock gap between the reveal of one live arrival and the
 * next. Tuned for the demo: at ~0.45s apart, ~15 elements unfold over
 * roughly seven seconds — comfortably inside the 60-second §24 window for
 * that beat, slow enough to follow each node/edge appear, fast enough
 * that it never drags. Kept in lock-step with the `--motion-graph-stagger`
 * token in `styles/tokens.css` (canvas draw code cannot read CSS custom
 * properties, so the value is declared here and cross-referenced there).
 */
export const GRAPH_GROWTH_STAGGER_MS = 450;

/**
 * Hard cap on how far past its real arrival time any single element's
 * reveal may be pushed. Without it, an unusually large burst (a resync,
 * or a much denser extraction than the demo's) would stretch into a
 * reveal tail tens of seconds long. Once the staggered queue is this far
 * ahead of real time, further arrivals snap to real time and appear
 * promptly as a group — the growth stays legible without ever stalling.
 *
 * At 8000ms / 450ms this fully staggers ~17 elements before it bunches —
 * comfortably more than the §24 demo's "six obligations, five implied"
 * plus their provenance edges and the conflict edge — while still
 * bounding a whole-graph resync's reveal tail to 8 seconds.
 */
export const GRAPH_GROWTH_MAX_LEAD_MS = 8000;

export interface GraphGrowthPacer {
  /**
   * Maps a live arrival's real timestamp to the time its growth
   * animation should begin.
   *
   * @param realArrivedAt - epoch ms the `/graph/stream` frame was
   *   received (normally `Date.now()`; injectable for tests).
   * @returns epoch ms at which this element should start animating in —
   *   equal to `realArrivedAt` for a well-spaced arrival, or a near-future
   *   time that keeps consecutive reveals `GRAPH_GROWTH_STAGGER_MS` apart
   *   during a burst, never more than `GRAPH_GROWTH_MAX_LEAD_MS` ahead of
   *   `realArrivedAt`.
   */
  schedule(realArrivedAt: number): number;
}

/**
 * Creates a fresh pacer. One instance is kept per `GraphExplorer` mount;
 * its only state is the timestamp of the last reveal it scheduled.
 *
 * @param staggerMs - reveal spacing; defaults to `GRAPH_GROWTH_STAGGER_MS`.
 * @param maxLeadMs - reveal lead cap; defaults to `GRAPH_GROWTH_MAX_LEAD_MS`.
 */
export function createGrowthPacer(
  staggerMs: number = GRAPH_GROWTH_STAGGER_MS,
  maxLeadMs: number = GRAPH_GROWTH_MAX_LEAD_MS,
): GraphGrowthPacer {
  // Far enough in the past that the first arrival is never delayed.
  let lastRevealAt = Number.NEGATIVE_INFINITY;

  return {
    schedule(realArrivedAt: number): number {
      // At least `staggerMs` after the previous reveal, but never earlier
      // than the arrival itself…
      const staggered = Math.max(realArrivedAt, lastRevealAt + staggerMs);
      // …and never pushed more than `maxLeadMs` past real arrival.
      const revealAt = Math.min(staggered, realArrivedAt + maxLeadMs);
      lastRevealAt = revealAt;
      return revealAt;
    },
  };
}
