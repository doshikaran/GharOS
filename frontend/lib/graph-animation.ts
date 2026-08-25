/**
 * Pure arrival-animation math for the graph canvas's live growth effect
 * (Phase 6 — "the one place motion carries meaning in the whole demo").
 * Kept dependency-free so it is trivially unit-testable without a canvas.
 *
 * Mirrors `--motion-graph-grow` (600ms, `styles/tokens.css`) — CSS custom
 * properties aren't readable from canvas draw code, so this duration is
 * declared here and documented as tracking that token's value.
 */

export const GRAPH_GROW_DURATION_MS = 600;

/** Cubic ease-out — starts fast, settles gently, matching
 * `--motion-ease-emphasized`'s spirit for an "arriving" motion. */
function easeOutCubic(t: number): number {
  const clamped = Math.min(1, Math.max(0, t));
  return 1 - Math.pow(1 - clamped, 3);
}

export interface ArrivalProgress {
  /** 0 at the instant of arrival, 1 once fully settled. Eased. */
  readonly eased: number;
  /** Convenience: opacity to draw at (mirrors `eased`). */
  readonly opacity: number;
  /** Convenience: scale to draw at — starts small (0.35x) and grows to 1x,
   * so the enter reads as a deliberate "arriving" motion rather than a
   * plain fade. */
  readonly scale: number;
  /** True once `eased` has reached 1 — the caller can stop special-casing
   * this id's draw call once true. */
  readonly settled: boolean;
}

const ARRIVAL_START_SCALE = 0.35;

/**
 * Computes how a newly-arrived node/edge should currently be drawn, given
 * when it arrived (`arrivedAt`, epoch ms) and the current time.
 *
 * @param now - current epoch ms (injectable for deterministic tests).
 * @param arrivedAt - epoch ms the element arrived via the live stream.
 * @param durationMs - total animation duration; defaults to `GRAPH_GROW_DURATION_MS`.
 */
export function computeArrivalProgress(
  now: number,
  arrivedAt: number,
  durationMs: number = GRAPH_GROW_DURATION_MS,
): ArrivalProgress {
  const linear = durationMs <= 0 ? 1 : (now - arrivedAt) / durationMs;
  const eased = easeOutCubic(linear);
  return {
    eased,
    opacity: eased,
    scale: ARRIVAL_START_SCALE + (1 - ARRIVAL_START_SCALE) * eased,
    settled: linear >= 1,
  };
}
