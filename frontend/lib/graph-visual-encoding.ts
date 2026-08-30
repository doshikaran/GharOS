/**
 * Node/edge visual encoding for the graph canvas (Phase 6 brief item 1).
 *
 * Node types: 18 types must "stay visually distinguishable — use shape or
 * icon plus color, not color alone, for accessibility". Every one of the
 * 18 `NodeType`s below gets a unique (geometry, fillMode) combination —
 * never relying on color alone even within a category that shares a color
 * token — plus a colour token for at-a-glance category grouping.
 *
 * Edge derivation: reuses `DerivationBadge`'s already-established
 * solid/dashed/dotted-by-derivation convention exactly (component doc
 * comment: "the same solid/dashed/dotted border convention used to style
 * graph edges by derivation tag, so this badge and the graph visualisation
 * teach the same visual language") — never reinvented here.
 *
 * Conflict edges (`is_conflict: true`) always render in `--edge-conflict`
 * with a substantially thicker stroke than any non-conflict edge,
 * regardless of derivation — "unmissable" per Gate 6's literal wording,
 * not just a colour swap that could still blend in.
 *
 * All colours are CSS custom-property *names* here (never resolved hex) —
 * `resolveColorToken` (this module) reads the real computed value from the
 * DOM at draw time, so light/dark theme switching is picked up for free
 * with zero raw hex anywhere in this file.
 */

import type { Derivation, NodeType } from "./graph-types";

// ---------------------------------------------------------------------------
// Node geometry
// ---------------------------------------------------------------------------

export type NodeGeometry =
  | "circle"
  | "diamond"
  | "triangle-up"
  | "triangle-down"
  | "square"
  | "hexagon"
  | "pentagon"
  | "star"
  | "cross"
  | "rounded-rect"
  | "x-mark";

export type NodeFillMode = "filled" | "outline" | "filled-with-dot";

export interface NodeVisual {
  readonly geometry: NodeGeometry;
  readonly fillMode: NodeFillMode;
  /** CSS custom-property name, e.g. "--royal-primary". */
  readonly colorToken: string;
}

// Colour = category tint (--graph-* palette, or a semantic state colour
// where the meaning is real: red CONSTRAINT, amber OBLIGATION, green
// ACTION/APPROVAL). Geometry + fillMode still uniquely identify all 18
// types, so nothing relies on colour alone.
export const NODE_VISUALS: Record<NodeType, NodeVisual> = {
  PERSON: { geometry: "circle", fillMode: "filled", colorToken: "--graph-1" },
  CONSTRAINT: { geometry: "diamond", fillMode: "filled", colorToken: "--state-danger" },
  OBLIGATION: { geometry: "triangle-up", fillMode: "filled", colorToken: "--state-warning" },
  LEDGER_EVENT: { geometry: "square", fillMode: "filled", colorToken: "--graph-5" },
  RECURRING_COMMITMENT: { geometry: "hexagon", fillMode: "filled", colorToken: "--graph-5" },
  VENDOR: { geometry: "pentagon", fillMode: "filled", colorToken: "--graph-2" },
  PROVIDER: { geometry: "circle", fillMode: "outline", colorToken: "--graph-2" },
  DECISION: { geometry: "star", fillMode: "filled", colorToken: "--graph-3" },
  BRANCH: { geometry: "triangle-down", fillMode: "filled", colorToken: "--graph-3" },
  COUNCIL_POSITION: { geometry: "cross", fillMode: "filled", colorToken: "--graph-3" },
  OUTCOME: { geometry: "diamond", fillMode: "outline", colorToken: "--graph-3" },
  SOURCE_DOCUMENT: { geometry: "rounded-rect", fillMode: "filled", colorToken: "--ink-secondary" },
  ACTION_RECORD: { geometry: "circle", fillMode: "filled-with-dot", colorToken: "--state-success" },
  APPROVAL_REQUEST: { geometry: "hexagon", fillMode: "outline", colorToken: "--state-success" },
  PURCHASE_ITEM: { geometry: "triangle-up", fillMode: "outline", colorToken: "--graph-5" },
  PATTERN: { geometry: "x-mark", fillMode: "filled", colorToken: "--graph-8" },
  ATTENDANCE_RECORD: { geometry: "square", fillMode: "outline", colorToken: "--graph-7" },
  VALUATION_PROFILE: { geometry: "star", fillMode: "outline", colorToken: "--graph-3" },
};

// ---------------------------------------------------------------------------
// Edge derivation styling — mirrors DerivationBadge exactly
// ---------------------------------------------------------------------------

export interface EdgeDerivationVisual {
  /** Canvas `setLineDash` pattern. Empty = solid. */
  readonly dash: readonly number[];
  readonly colorToken: string;
}

export const EDGE_DERIVATION_VISUALS: Record<Derivation, EdgeDerivationVisual> = {
  extracted: { dash: [], colorToken: "--derivation-extracted" },
  inferred: { dash: [8, 5], colorToken: "--derivation-inferred" },
  ambiguous: { dash: [1.5, 4], colorToken: "--derivation-ambiguous" },
};

/** Fallback for an edge with no derivation set (should not occur per the
 * frozen wire contract, but a draw routine must never throw on real data). */
export const EDGE_DEFAULT_VISUAL: EdgeDerivationVisual = {
  dash: [],
  colorToken: "--ink-muted",
};

export const EDGE_CONFLICT_COLOR_TOKEN = "--edge-conflict";
export const EDGE_BASE_LINE_WIDTH = 1.25;
/** Conflict edges render at 3x the base line width — "unmissable", not a
 * colour swap that could still blend in (Gate 6's literal wording). */
export const EDGE_CONFLICT_LINE_WIDTH = EDGE_BASE_LINE_WIDTH * 3;

// ---------------------------------------------------------------------------
// CSS custom-property -> real computed colour, cached per theme
// ---------------------------------------------------------------------------

let cachedTheme: string | null = null;
let colorCache = new Map<string, string>();

/**
 * Resolves a CSS custom-property name (e.g. `"--royal-primary"`) to its
 * real computed colour string, for use as a canvas `fillStyle`/`strokeStyle`
 * (canvas does not participate in the CSS cascade, so `var(--x)` is not a
 * valid canvas colour — it must be resolved). Cached per call, invalidated
 * automatically whenever `document.documentElement`'s resolved theme
 * (`data-theme` attribute, falling back to `"system"`) changes, so a theme
 * toggle is picked up without a stale palette.
 */
export function resolveColorToken(token: string): string {
  if (typeof document === "undefined") return "#000000";
  const currentTheme = document.documentElement.getAttribute("data-theme") ?? "system";
  if (currentTheme !== cachedTheme) {
    cachedTheme = currentTheme;
    colorCache = new Map();
  }
  const cached = colorCache.get(token);
  if (cached !== undefined) return cached;
  const value = getComputedStyle(document.documentElement).getPropertyValue(token).trim();
  const resolved = value.length > 0 ? value : "#000000";
  colorCache.set(token, resolved);
  return resolved;
}

// ---------------------------------------------------------------------------
// Shape path construction — assumes the canvas context is already
// translated to the node's centre; draws a closed path of the given
// geometry inscribed in `radius`, ready for the caller to fill/stroke.
// ---------------------------------------------------------------------------

function polygonPath(ctx: CanvasRenderingContext2D, radius: number, sides: number, rotation: number): void {
  ctx.beginPath();
  for (let i = 0; i < sides; i += 1) {
    const angle = rotation + (i * 2 * Math.PI) / sides;
    const x = radius * Math.cos(angle);
    const y = radius * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

function starPath(ctx: CanvasRenderingContext2D, radius: number): void {
  const points = 5;
  const innerRadius = radius * 0.45;
  ctx.beginPath();
  for (let i = 0; i < points * 2; i += 1) {
    const r = i % 2 === 0 ? radius : innerRadius;
    const angle = -Math.PI / 2 + (i * Math.PI) / points;
    const x = r * Math.cos(angle);
    const y = r * Math.sin(angle);
    if (i === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  }
  ctx.closePath();
}

/**
 * Draws `geometry`'s path (or, for line-based geometries with no fillable
 * interior, its strokes directly) at the given `radius`, and fills/strokes
 * it per `fillMode` using `strokeStyle`/`fillStyle` the caller has already
 * set. Assumes the context is translated to the node centre.
 */
export function drawNodeGeometry(
  ctx: CanvasRenderingContext2D,
  geometry: NodeGeometry,
  fillMode: NodeFillMode,
  radius: number,
): void {
  switch (geometry) {
    case "circle":
      ctx.beginPath();
      ctx.arc(0, 0, radius, 0, Math.PI * 2);
      break;
    case "diamond":
      polygonPath(ctx, radius, 4, 0);
      break;
    case "square":
      polygonPath(ctx, radius, 4, Math.PI / 4);
      break;
    case "triangle-up":
      polygonPath(ctx, radius, 3, -Math.PI / 2);
      break;
    case "triangle-down":
      polygonPath(ctx, radius, 3, Math.PI / 2);
      break;
    case "pentagon":
      polygonPath(ctx, radius, 5, -Math.PI / 2);
      break;
    case "hexagon":
      polygonPath(ctx, radius, 6, 0);
      break;
    case "star":
      starPath(ctx, radius);
      break;
    case "rounded-rect": {
      const side = radius * 1.6;
      ctx.beginPath();
      ctx.roundRect(-side / 2, -side / 2, side, side, radius * 0.3);
      break;
    }
    case "cross": {
      const arm = radius * 0.42;
      ctx.beginPath();
      ctx.moveTo(-arm, -radius);
      ctx.lineTo(arm, -radius);
      ctx.lineTo(arm, -arm);
      ctx.lineTo(radius, -arm);
      ctx.lineTo(radius, arm);
      ctx.lineTo(arm, arm);
      ctx.lineTo(arm, radius);
      ctx.lineTo(-arm, radius);
      ctx.lineTo(-arm, arm);
      ctx.lineTo(-radius, arm);
      ctx.lineTo(-radius, -arm);
      ctx.lineTo(-arm, -arm);
      ctx.closePath();
      break;
    }
    case "x-mark": {
      const inset = radius * 0.7;
      ctx.beginPath();
      ctx.moveTo(-inset, -inset);
      ctx.lineTo(inset, inset);
      ctx.moveTo(inset, -inset);
      ctx.lineTo(-inset, inset);
      ctx.stroke();
      return; // line-based: no fillable interior, nothing more to do
    }
  }

  if (fillMode === "outline") {
    ctx.stroke();
    return;
  }
  ctx.fill();
  if (fillMode === "filled-with-dot") {
    ctx.beginPath();
    ctx.arc(0, 0, radius * 0.3, 0, Math.PI * 2);
    ctx.fillStyle = resolveColorToken("--on-royal");
    ctx.fill();
  }
}
