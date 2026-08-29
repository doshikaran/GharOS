"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { fetchGraphSnapshot, GraphApiError } from "@/lib/graph-api";
import {
  buildDecisionReplay,
  listDecisions,
  searchDecisions,
  type DecisionRecord,
} from "@/lib/council-history";
import type { GraphSnapshot } from "@/lib/graph-types";
import { DecisionReplayPanel } from "./DecisionReplayPanel";
import styles from "./CouncilHistoryBrowser.module.css";

export interface CouncilHistoryBrowserProps {
  readonly baseUrl: string;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

/**
 * The historical decision browser — "why did we buy this car?" (spec
 * §12.4's own two-years-later promise, PHASES.md Phase 12 E4 work item).
 *
 * No new backend endpoint (ADR-019's closing note, `lib/council-history.ts`'s
 * own module docstring): `GET /graph/snapshot`, the same call
 * `GraphExplorer`/`LedgerExplorer` already make, already carries every
 * `DECISION`/`BRANCH`/`COUNCIL_POSITION` node and `conceded_by` edge
 * generically. This component fetches that snapshot once and filters/joins
 * it client-side via `lib/council-history.ts`'s pure functions — the same
 * split `LedgerExplorer` already uses for its own live-data half.
 *
 * Institutional memory as a UI feature, not just a data model: selecting a
 * past decision surfaces the actual `Decision` node, every `Branch` it
 * weighed, every `CouncilPosition` that named it, and who is recorded as
 * having conceded — never a re-summarised paragraph standing in for the
 * original record.
 */
export function CouncilHistoryBrowser({ baseUrl }: CouncilHistoryBrowserProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [snapshot, setSnapshot] = useState<GraphSnapshot>({ nodes: [], edges: [] });
  const [query, setQuery] = useState("");
  const [selectedDecisionId, setSelectedDecisionId] = useState<string | null>(null);
  const searchInputId = useId();

  useEffect(() => {
    let cancelled = false;
    fetchGraphSnapshot(baseUrl)
      .then((result) => {
        if (cancelled) return;
        setSnapshot(result);
        setLoadState({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load past decisions.";
        setLoadState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  const allDecisions = useMemo(() => listDecisions(snapshot), [snapshot]);
  const visibleDecisions: readonly DecisionRecord[] = useMemo(
    () => searchDecisions(allDecisions, query),
    [allDecisions, query],
  );
  const replay = useMemo(
    () => (selectedDecisionId ? buildDecisionReplay(snapshot, selectedDecisionId) : null),
    [snapshot, selectedDecisionId],
  );

  if (loadState.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading past council decisions…
      </p>
    );
  }

  if (loadState.status === "error") {
    return (
      <p className={styles.status} role="alert">
        Could not load past decisions: {loadState.message}
      </p>
    );
  }

  return (
    <div className={styles.browser}>
      <div className={styles.searchRow}>
        <label htmlFor={searchInputId} className={styles.srOnly}>
          Search past decisions by question
        </label>
        <input
          id={searchInputId}
          type="search"
          className={styles.searchInput}
          placeholder="e.g. why did we buy this car?"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
      </div>

      {allDecisions.length === 0 ? (
        <p className={styles.empty}>No past council decisions recorded yet.</p>
      ) : (
        <div className={styles.layout}>
          <ul className={styles.decisionList} aria-label="Past decisions">
            {visibleDecisions.length === 0 && <li className={styles.empty}>No decision matches that search.</li>}
            {visibleDecisions.map((decision) => (
              <li key={decision.id}>
                <button
                  type="button"
                  className={`${styles.decisionButton} ${decision.id === selectedDecisionId ? styles.decisionButtonActive : ""}`}
                  aria-pressed={decision.id === selectedDecisionId}
                  onClick={() => setSelectedDecisionId(decision.id)}
                >
                  <span className={styles.decisionQuestion}>{decision.question}</span>
                  <span className={styles.decisionStatus}>{decision.status || "unknown"}</span>
                </button>
              </li>
            ))}
          </ul>

          <div className={styles.detail}>
            {replay ? (
              <DecisionReplayPanel replay={replay} />
            ) : (
              <p className={styles.emptyDetail}>Select a past decision to replay its full record.</p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
