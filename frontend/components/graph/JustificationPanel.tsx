"use client";

import { useEffect, useRef, useState } from "react";
import { fetchJustification, GraphApiError } from "@/lib/graph-api";
import type { GraphNode, JustificationResponse } from "@/lib/graph-types";
import { connectorPhrase } from "./justification-phrasing";
import type { HighlightedPath } from "./GraphCanvas";
import styles from "./JustificationPanel.module.css";

export interface JustificationPanelProps {
  readonly baseUrl: string;
  readonly rootNodeId: string;
  readonly nodesById: ReadonlyMap<string, GraphNode>;
  /** Called with the node/edge ids to emphasise on the graph canvas once
   * the chain loads, and with `null` on unmount/root-node change so the
   * dimming clears — the path explainer's second required rendering
   * (Phase 6 item 4: "visible on the graph itself, not just a text dump"). */
  readonly onHighlightChange: (highlight: HighlightedPath | null) => void;
  readonly onClose: () => void;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; result: JustificationResponse };

function labelFor(nodesById: ReadonlyMap<string, GraphNode>, nodeId: string): string {
  return nodesById.get(nodeId)?.label ?? nodeId;
}

/**
 * The path explainer (Phase 6 item 4): fetches
 * `/graph/nodes/{id}/justification` and renders the walkable chain two
 * ways at once — a legible, ordered, plain-language list here, and (via
 * `onHighlightChange`) the same chain highlighted directly on the graph
 * canvas.
 */
export function JustificationPanel({ baseUrl, rootNodeId, nodesById, onHighlightChange, onClose }: JustificationPanelProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });

  // Read via a ref (kept fresh in its own effect, never during render) so
  // the fetch effect below doesn't need `onHighlightChange` in its
  // dependency array — the caller (`GraphExplorer`) mounts one
  // `JustificationPanel` per `rootNodeId` via `key={explainingNodeId}`, so
  // "loading" is simply this component's initial state on every fresh
  // root-node selection; no synchronous reset-to-loading inside the effect
  // is needed.
  const onHighlightChangeRef = useRef(onHighlightChange);
  useEffect(() => {
    onHighlightChangeRef.current = onHighlightChange;
  });

  useEffect(() => {
    let cancelled = false;

    fetchJustification(baseUrl, rootNodeId)
      .then((result) => {
        if (cancelled) return;
        setState({ status: "loaded", result });
        const nodeIds = new Set(result.steps.map((step) => step.node_id));
        const edgeIds = new Set(
          result.steps.flatMap((step) => (step.via_edge ? [step.via_edge.id] : [])),
        );
        onHighlightChangeRef.current({ nodeIds, edgeIds });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load justification.";
        setState({ status: "error", message });
      });

    return () => {
      cancelled = true;
      onHighlightChangeRef.current(null);
    };
  }, [baseUrl, rootNodeId]);

  return (
    <section className={styles.panel} aria-label="Path explainer">
      <div className={styles.header}>
        <h3 className={styles.title}>Why is this here?</h3>
        <button type="button" className={styles.closeButton} onClick={onClose} aria-label="Close path explainer">
          ×
        </button>
      </div>

      {state.status === "loading" && (
        <p className={styles.status} role="status">
          Tracing the justification chain…
        </p>
      )}

      {state.status === "error" && (
        <p className={styles.status} role="alert">
          Could not load the justification chain: {state.message}
        </p>
      )}

      {state.status === "loaded" && (
        <>
          <ol className={styles.chain}>
            {state.result.steps.map((step) => {
              const label = labelFor(nodesById, step.node_id);
              if (step.via_edge === null) {
                return (
                  <li key={step.node_id} className={styles.rootStep}>
                    {label}
                  </li>
                );
              }
              const childIsFromId = step.via_edge.from_id === step.node_id;
              const phrase = connectorPhrase(step.via_edge.type, childIsFromId);
              return (
                <li key={step.node_id} className={styles.childStep}>
                  <span className={styles.connector}>
                    ← {phrase} ←
                  </span>{" "}
                  {label}
                </li>
              );
            })}
          </ol>

          {state.result.source_documents.length > 0 && (
            <div className={styles.sources}>
              <h4 className={styles.sourcesHeading}>Source documents</h4>
              <ul className={styles.sourcesList}>
                {state.result.source_documents.map((doc) => (
                  <li key={doc.id}>
                    {doc.channel}
                    {doc.region ? `, ${doc.region}` : ""}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
