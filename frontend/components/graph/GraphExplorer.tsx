"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { fetchGraphSnapshot, GraphApiError } from "@/lib/graph-api";
import { subscribeToGraphStream } from "@/lib/graph-stream";
import { applyGraphFilters, EMPTY_GRAPH_FILTER_STATE, type GraphFilterState } from "@/lib/graph-filters";
import { applySnapshot, applyStreamEvent, createEmptyGraphState, listEdges, listNodes } from "@/lib/graph-state";
import { GraphCanvas, type HighlightedPath } from "./GraphCanvas";
import { GraphFilters, type GraphPersonOption } from "./GraphFilters";
import { GraphLegend } from "./GraphLegend";
import { NodeInspector } from "./NodeInspector";
import { JustificationPanel } from "./JustificationPanel";
import styles from "./GraphExplorer.module.css";

export interface GraphExplorerProps {
  readonly baseUrl: string;
  /** Deep-link target: when set (from `/graph?node=<id>` — used by the
   * ingestion run view's "new node" links), that node's inspector opens
   * once the graph has loaded. */
  readonly initialSelectedNodeId?: string | null;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

/**
 * Top-level stateful orchestrator for `/graph` — a client component
 * (fetch + SSE + local state) kept separate from `app/graph/page.tsx`,
 * which stays a Server Component so it can export page `metadata` (same
 * split as `StatusBoard`/`ApprovalsBoard`).
 *
 * Owns the load sequence Phase 6 requires exactly: `/graph/snapshot`
 * loads once, un-animated, as the baseline; `/graph/stream` is subscribed
 * to only *after* that baseline render, so every event it delivers is a
 * genuinely new arrival, never a replay — this is what makes the graph
 * visibly "being built", not pre-seeded or replayed, when watched cold.
 */
export function GraphExplorer({ baseUrl, initialSelectedNodeId = null }: GraphExplorerProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [graphState, setGraphState] = useState(createEmptyGraphState);
  const [filters, setFilters] = useState<GraphFilterState>(EMPTY_GRAPH_FILTER_STATE);
  // Seeded from `/graph?node=<id>` (the ingestion run view's node links).
  // `app/(shell)/graph/page.tsx` keys this component on that value, so a
  // later deep link with a different node remounts and re-seeds here.
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(initialSelectedNodeId);
  const [explainingNodeId, setExplainingNodeId] = useState<string | null>(null);
  const [highlightedPath, setHighlightedPath] = useState<HighlightedPath | null>(null);

  // 1. Load the baseline snapshot once.
  useEffect(() => {
    let cancelled = false;
    fetchGraphSnapshot(baseUrl)
      .then((snapshot) => {
        if (cancelled) return;
        setGraphState((prev) => applySnapshot(prev, snapshot));
        setLoadState({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load the graph.";
        setLoadState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  // 2. Subscribe to live mutations only after the baseline has loaded —
  // never before, so nothing from the snapshot is ever mistaken for a live
  // arrival (see this component's doc comment).
  useEffect(() => {
    if (loadState.status !== "ready") return undefined;
    const unsubscribe = subscribeToGraphStream(baseUrl, {
      onEvent: (event) => {
        setGraphState((prev) => applyStreamEvent(prev, event));
      },
      onError: (error) => {
        // A stream hiccup never invalidates the already-loaded graph — log
        // and keep the existing render rather than tearing anything down.
        console.error("graph stream error", error);
      },
    });
    return unsubscribe;
  }, [baseUrl, loadState.status]);

  const allNodes = useMemo(() => listNodes(graphState), [graphState]);
  const allEdges = useMemo(() => listEdges(graphState), [graphState]);
  const nodesById = useMemo(() => new Map(allNodes.map((node) => [node.id, node] as const)), [allNodes]);

  const { nodes: visibleNodes, edges: visibleEdges } = useMemo(
    () => applyGraphFilters(allNodes, allEdges, filters),
    [allNodes, allEdges, filters],
  );

  const people: GraphPersonOption[] = useMemo(
    () =>
      allNodes
        .filter((node) => node.type === "PERSON")
        .map((node) => ({ id: node.id, label: node.label }))
        .sort((a, b) => a.label.localeCompare(b.label)),
    [allNodes],
  );

  const selectedNode = selectedNodeId ? (nodesById.get(selectedNodeId) ?? null) : null;

  const handleSelectNode = useCallback((nodeId: string | null) => {
    setSelectedNodeId(nodeId);
    setExplainingNodeId(null);
  }, []);

  const handleExplain = useCallback((nodeId: string) => {
    setExplainingNodeId(nodeId);
  }, []);

  const handleCloseInspector = useCallback(() => {
    setSelectedNodeId(null);
    setExplainingNodeId(null);
  }, []);

  const handleCloseJustification = useCallback(() => {
    setExplainingNodeId(null);
  }, []);

  if (loadState.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading the household knowledge graph…
      </p>
    );
  }

  if (loadState.status === "error") {
    return (
      <p className={styles.status} role="alert">
        Could not load the graph: {loadState.message}
      </p>
    );
  }

  return (
    <div className={styles.layout}>
      <div className={styles.sidebar}>
        <GraphFilters value={filters} onChange={setFilters} people={people} />
        <GraphLegend />
      </div>

      <div className={styles.main}>
        <p className={styles.summary} role="status" aria-live="polite">
          Showing {visibleNodes.length} of {allNodes.length} nodes, {visibleEdges.length} of {allEdges.length} edges.
        </p>
        <GraphCanvas
          nodes={visibleNodes}
          edges={visibleEdges}
          liveArrivedAt={graphState.liveArrivedAt}
          selectedNodeId={selectedNodeId}
          onSelectNode={handleSelectNode}
          highlightedPath={highlightedPath}
          className={styles.canvas}
        />
        {/* Screen-reader-accessible mirror of the canvas's node set, canvas
            content carries no semantics of its own, and this also gives a
            stable, DOM-visible marker of which ids arrived live vs. from
            the baseline snapshot (see GraphExplorer.test.tsx). */}
        <ul className={styles.srOnly} data-testid="graph-node-list">
          {visibleNodes.map((node) => (
            <li key={node.id} data-node-id={node.id} data-arrived-live={graphState.liveArrivedAt.has(node.id)}>
              {node.label} ({node.type})
            </li>
          ))}
        </ul>
      </div>

      {(selectedNode || explainingNodeId) && (
        <div className={styles.details}>
          {selectedNode && (
            <NodeInspector node={selectedNode} baseUrl={baseUrl} onClose={handleCloseInspector} onExplain={handleExplain} />
          )}
          {explainingNodeId && (
            <JustificationPanel
              key={explainingNodeId}
              baseUrl={baseUrl}
              rootNodeId={explainingNodeId}
              nodesById={nodesById}
              onHighlightChange={setHighlightedPath}
              onClose={handleCloseJustification}
            />
          )}
        </div>
      )}
    </div>
  );
}
