"use client";

import { useEffect, useRef, useState } from "react";
import { forceCenter, select, zoom, zoomIdentity, type ZoomTransform } from "d3";
import type { GraphEdge, GraphNode } from "@/lib/graph-types";
import { computeArrivalProgress, GRAPH_GROW_DURATION_MS } from "@/lib/graph-animation";
import { findNodeAtPoint } from "@/lib/graph-hit-test";
import {
  createGraphSimulation,
  isSimulationActive,
  reheatSimulation,
  stepSimulation,
  type SimLink,
  type SimNode,
} from "@/lib/graph-simulation";
import {
  drawNodeGeometry,
  EDGE_CONFLICT_COLOR_TOKEN,
  EDGE_CONFLICT_LINE_WIDTH,
  EDGE_BASE_LINE_WIDTH,
  EDGE_DEFAULT_VISUAL,
  EDGE_DERIVATION_VISUALS,
  NODE_VISUALS,
  resolveColorToken,
} from "@/lib/graph-visual-encoding";
import styles from "./GraphCanvas.module.css";

export interface HighlightedPath {
  readonly nodeIds: ReadonlySet<string>;
  readonly edgeIds: ReadonlySet<string>;
}

export interface GraphCanvasProps {
  readonly nodes: readonly GraphNode[];
  readonly edges: readonly GraphEdge[];
  /** id -> epoch ms it arrived via the live stream (`GraphState.liveArrivedAt`).
   * Only these ids ever animate — see `lib/graph-animation.ts`. */
  readonly liveArrivedAt: ReadonlyMap<string, number>;
  readonly selectedNodeId: string | null;
  readonly onSelectNode: (nodeId: string | null) => void;
  /** Path-explainer highlight (Phase 6 item 4): when set, the named
   * nodes/edges render at full emphasis and everything else dims. */
  readonly highlightedPath: HighlightedPath | null;
  readonly className?: string;
}

const DRAW_NODE_RADIUS = 9;
const COLLIDE_RADIUS = 15;
const DIMMED_ALPHA = 0.15;
const DEFAULT_WIDTH = 800;
const DEFAULT_HEIGHT = 600;

/**
 * The force-directed graph, rendered on a single HTML5 canvas with a
 * hand-rolled draw loop driving a stopped `d3-force` simulation — not one
 * SVG element per node/edge. At 500+ demo-scale nodes, per-element SVG DOM
 * nodes are the bottleneck (layout/paint cost scales with element count,
 * not draw-call count); a canvas 2D context pays one draw call per
 * node/edge per frame regardless of DOM size, which is what stays smooth
 * at this scale (`graph-simulation.test.ts` measures the underlying
 * simulation's own per-frame cost directly).
 *
 * The draw loop is deliberately always-on for the component's lifetime
 * rather than a start/stop state machine keyed off "is anything currently
 * animating" — at demo scale (hundreds of nodes, not thousands) a
 * continuous `requestAnimationFrame` loop that skips physics stepping once
 * `isSimulationActive` goes false, but still redraws every frame, is
 * simple, correct, and cheap enough; the pause/resume version would save
 * a marginal amount of idle CPU at the cost of real bug surface (missed
 * wake-ups on filter/selection/highlight changes) for no visible demo
 * benefit.
 *
 * All per-render data (props) reaches the draw loop and click handler via
 * refs updated in their own effect, never read directly during render —
 * `d3-force`'s simulation object itself is created exactly once via lazy
 * `useState` initialization (the React-sanctioned way to get a stable,
 * one-time value without touching a ref during render).
 */
export function GraphCanvas({
  nodes,
  edges,
  liveArrivedAt,
  selectedNodeId,
  onSelectNode,
  highlightedPath,
  className,
}: GraphCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [sim] = useState(() =>
    createGraphSimulation([], [], { width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT, nodeRadius: COLLIDE_RADIUS }),
  );
  const simNodesByIdRef = useRef<Map<string, SimNode>>(new Map());
  const transformRef = useRef<ZoomTransform>(zoomIdentity);
  const sizeRef = useRef({ width: DEFAULT_WIDTH, height: DEFAULT_HEIGHT });

  // Latest-props refs so the one persistent rAF loop and the click handler
  // (both defined once, inside the mount-only effect below) always read
  // current data without needing that effect to re-run every render.
  // Updated from their own effect (never during render) — an effect with
  // no dependency array runs after every render, which is exactly the
  // "always keep this in sync" semantics these refs need.
  const nodesRef = useRef(nodes);
  const edgesRef = useRef(edges);
  const liveArrivedAtRef = useRef(liveArrivedAt);
  const selectedNodeIdRef = useRef(selectedNodeId);
  const highlightedPathRef = useRef(highlightedPath);
  const onSelectNodeRef = useRef(onSelectNode);
  useEffect(() => {
    nodesRef.current = nodes;
    edgesRef.current = edges;
    liveArrivedAtRef.current = liveArrivedAt;
    selectedNodeIdRef.current = selectedNodeId;
    highlightedPathRef.current = highlightedPath;
    onSelectNodeRef.current = onSelectNode;
  });

  // Reconcile the simulation's node/link arrays whenever the visible
  // node/edge id-sets change, reusing existing SimNode objects (and their
  // settled x/y) for ids that survive, so an unrelated filter toggle never
  // resets the whole layout.
  useEffect(() => {
    const existing = simNodesByIdRef.current;
    const nextIds = new Set(nodes.map((node) => node.id));

    for (const id of [...existing.keys()]) {
      if (!nextIds.has(id)) existing.delete(id);
    }
    for (const node of nodes) {
      if (!existing.has(node.id)) existing.set(node.id, { id: node.id });
    }

    const simNodes = nodes.map((node) => existing.get(node.id) as SimNode);
    const simLinks: SimLink[] = edges.map((edge) => ({
      id: edge.id,
      source: edge.from_id,
      target: edge.to_id,
    }));

    sim.nodes(simNodes);
    (sim.force("link") as unknown as { links: (links: SimLink[]) => void }).links(simLinks);
    reheatSimulation(sim);
  }, [sim, nodes, edges]);

  // One-time setup: canvas sizing, the draw loop, and pan/zoom + click
  // interaction. Deliberately depends on nothing but the stable `sim`
  // value, so it runs exactly once per mount — all per-render data flows
  // in via the refs above.
  useEffect(() => {
    const container = containerRef.current;
    const canvas = canvasRef.current;
    if (!container || !canvas) return;

    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      sizeRef.current = { width: rect.width, height: rect.height };
      canvas.width = Math.max(1, Math.round(rect.width * dpr));
      canvas.height = Math.max(1, Math.round(rect.height * dpr));
      canvas.style.width = `${rect.width}px`;
      canvas.style.height = `${rect.height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      (sim.force("center") as ReturnType<typeof forceCenter>).x(rect.width / 2).y(rect.height / 2);
    };
    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    const zoomBehavior = zoom<HTMLCanvasElement, unknown>()
      .scaleExtent([0.15, 4])
      .on("zoom", (event) => {
        transformRef.current = event.transform;
      });
    select(canvas).call(zoomBehavior);

    const handleClick = (event: MouseEvent) => {
      const rect = canvas.getBoundingClientRect();
      const t = transformRef.current;
      const worldX = (event.clientX - rect.left - t.x) / t.k;
      const worldY = (event.clientY - rect.top - t.y) / t.k;
      const simNodes = [...simNodesByIdRef.current.values()];
      const hitId = findNodeAtPoint(simNodes, worldX, worldY, DRAW_NODE_RADIUS + 4);
      onSelectNodeRef.current(hitId);
    };
    canvas.addEventListener("click", handleClick);

    let animationFrameId: number;
    const draw = () => {
      const { width, height } = sizeRef.current;
      ctx.save();
      ctx.clearRect(0, 0, width, height);
      ctx.fillStyle = resolveColorToken("--surface-base");
      ctx.fillRect(0, 0, width, height);

      const t = transformRef.current;
      ctx.translate(t.x, t.y);
      ctx.scale(t.k, t.k);

      const now = Date.now();
      const highlight = highlightedPathRef.current;
      const selectedId = selectedNodeIdRef.current;
      const arrivals = liveArrivedAtRef.current;
      const simNodesById = simNodesByIdRef.current;
      const edgeById = new Map(edgesRef.current.map((edge) => [edge.id, edge] as const));

      // Edges first, under the nodes.
      for (const edge of edgeById.values()) {
        const from = simNodesById.get(edge.from_id);
        const to = simNodesById.get(edge.to_id);
        if (!from || from.x === undefined || from.y === undefined) continue;
        if (!to || to.x === undefined || to.y === undefined) continue;

        const derivationVisual = edge.derivation ? EDGE_DERIVATION_VISUALS[edge.derivation] : EDGE_DEFAULT_VISUAL;
        const isHighlighted = highlight ? highlight.edgeIds.has(edge.id) : true;
        const arrivedAt = arrivals.get(edge.id);
        const arrival = arrivedAt !== undefined ? computeArrivalProgress(now, arrivedAt, GRAPH_GROW_DURATION_MS) : null;

        ctx.save();
        ctx.globalAlpha = (isHighlighted ? 1 : DIMMED_ALPHA) * (arrival ? arrival.opacity : 1);
        ctx.strokeStyle = edge.is_conflict
          ? resolveColorToken(EDGE_CONFLICT_COLOR_TOKEN)
          : resolveColorToken(derivationVisual.colorToken);
        ctx.lineWidth = edge.is_conflict ? EDGE_CONFLICT_LINE_WIDTH : EDGE_BASE_LINE_WIDTH;
        ctx.setLineDash(derivationVisual.dash);
        ctx.beginPath();
        ctx.moveTo(from.x, from.y);
        ctx.lineTo(to.x, to.y);
        ctx.stroke();
        ctx.restore();
      }

      // Nodes on top.
      for (const node of nodesRef.current) {
        const simNode = simNodesById.get(node.id);
        if (!simNode || simNode.x === undefined || simNode.y === undefined) continue;

        const visual = NODE_VISUALS[node.type];
        const isHighlighted = highlight ? highlight.nodeIds.has(node.id) : true;
        const arrivedAt = arrivals.get(node.id);
        const arrival = arrivedAt !== undefined ? computeArrivalProgress(now, arrivedAt, GRAPH_GROW_DURATION_MS) : null;
        const scale = arrival ? arrival.scale : 1;
        const radius = DRAW_NODE_RADIUS * scale * (node.id === selectedId ? 1.35 : 1);

        ctx.save();
        ctx.translate(simNode.x, simNode.y);
        ctx.globalAlpha = (isHighlighted ? 1 : DIMMED_ALPHA) * (arrival ? arrival.opacity : 1);
        ctx.fillStyle = resolveColorToken(visual.colorToken);
        ctx.strokeStyle = resolveColorToken(visual.colorToken);
        ctx.lineWidth = 2;
        drawNodeGeometry(ctx, visual.geometry, visual.fillMode, radius);
        if (node.id === selectedId) {
          ctx.lineWidth = 2.5;
          ctx.strokeStyle = resolveColorToken("--accent-brass");
          ctx.stroke();
        }
        ctx.restore();
      }

      ctx.restore();
    };

    const frame = () => {
      if (isSimulationActive(sim)) stepSimulation(sim);
      draw();
      animationFrameId = requestAnimationFrame(frame);
    };
    animationFrameId = requestAnimationFrame(frame);

    return () => {
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      canvas.removeEventListener("click", handleClick);
      select(canvas).on(".zoom", null);
      sim.stop();
    };
  }, [sim]);

  return (
    <div ref={containerRef} className={[styles.container, className].filter(Boolean).join(" ")}>
      <canvas ref={canvasRef} role="img" aria-label="Household knowledge graph" className={styles.canvas} />
    </div>
  );
}
