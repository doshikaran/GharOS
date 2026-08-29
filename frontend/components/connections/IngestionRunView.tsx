"use client";

import Link from "next/link";
import { LoaderCircle } from "lucide-react";
import { Card } from "@/components/design-system/Card";
import {
  computeStatusCounts,
  graphNodeHref,
  ingestionSourceLabel,
  type DocumentIngestOutcome,
  type IngestionRunResult,
  type OAuthProvider,
} from "@/lib/connections";
import { IngestionStatusBadge, ingestionStatusLabel } from "./IngestionStatusBadge";
import { ReconnectPrompt } from "./ReconnectPrompt";
import styles from "./IngestionRunView.module.css";

/**
 * The live ingestion-run view (PHASES.md Phase 14.5, E4 brief). Pure and
 * presentational: `/connections` drives it from a `POST /ingest` call and
 * the `/voice` surface drives it from the `ingestion_run` frame
 * (ADR-023 §7), so the exact same component renders both paths — it is
 * extracted here for that reason.
 *
 * It renders an honest `IngestionRunResult`: a header with the per-status
 * `counts` and run timing, one row per `DocumentIngestOutcome` with a
 * distinct treatment per status, `INGESTED` rows deep-linking their new
 * node ids into `/graph`, and `ConnectorFailure` / `run_errors` shown
 * distinctly. An `is_auth_failure` failure becomes a reconnect prompt,
 * never a silent empty result.
 */
export type IngestionRunViewState =
  | { readonly phase: "idle" }
  | { readonly phase: "running"; readonly startedAtMs: number; readonly liveNodeIds: readonly string[] }
  | { readonly phase: "done"; readonly run: IngestionRunResult; readonly liveNodeIds: readonly string[] }
  | {
      readonly phase: "reconnect-required";
      readonly provider: OAuthProvider | null;
      readonly principal: string | null;
      readonly message: string;
    }
  | { readonly phase: "error"; readonly message: string; readonly detail?: string };

export interface IngestionRunViewProps {
  readonly state: IngestionRunViewState;
  /** Wired on `/connections` (kicks off a fresh OAuth consent); omitted
   * on `/voice`, where the prompt points back to the connections list. */
  readonly onReconnect?: (provider: OAuthProvider) => void;
  /** Injectable clock, for a deterministic "elapsed" figure in tests. */
  readonly now?: () => number;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${Math.max(0, Math.round(ms))} ms`;
  return `${(ms / 1000).toFixed(1)} s`;
}

function OutcomeRow({ outcome }: { outcome: DocumentIngestOutcome }) {
  return (
    <li className={styles.row} data-status={outcome.status}>
      <div className={styles.rowHead}>
        <span className={styles.source}>{ingestionSourceLabel(outcome.source)}</span>
        <IngestionStatusBadge status={outcome.status} />
      </div>

      {outcome.classified_type_id && (
        <p className={styles.typeLine}>
          Classified as <span className={styles.typeId}>{outcome.classified_type_id}</span>
        </p>
      )}

      {outcome.detail && <p className={styles.detail}>{outcome.detail}</p>}

      {outcome.external_ref && (
        <p className={styles.externalRef}>Source reference: {outcome.external_ref}</p>
      )}

      {outcome.status === "ingested" && outcome.new_node_ids.length > 0 && (
        <div className={styles.nodeLinks}>
          <span className={styles.nodeLinksLabel}>
            New {outcome.new_node_ids.length === 1 ? "node" : "nodes"} in the graph:
          </span>
          <ul className={styles.nodeLinkList}>
            {outcome.new_node_ids.map((nodeId) => (
              <li key={nodeId}>
                <Link href={graphNodeHref(nodeId)} className={styles.nodeLink}>
                  {nodeId}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}

      {outcome.status === "duplicate_skipped" && outcome.source_document_id && (
        <p className={styles.detail}>
          Matches the document first ingested as{" "}
          <Link href={graphNodeHref(outcome.source_document_id)} className={styles.nodeLink}>
            {outcome.source_document_id}
          </Link>
          . Nothing was written.
        </p>
      )}
    </li>
  );
}

export function IngestionRunView({ state, onReconnect, now = Date.now }: IngestionRunViewProps) {
  if (state.phase === "idle") {
    return (
      <p className={styles.idle} role="status">
        No scan has run yet. Connect an account and choose &ldquo;Scan the last 24 hours&rdquo;, drop in a file, or
        pick from Drive.
      </p>
    );
  }

  if (state.phase === "running") {
    const elapsed = formatDuration(now() - state.startedAtMs);
    return (
      <Card className={styles.card}>
        <div className={styles.runningHead} role="status" aria-live="polite">
          <LoaderCircle size={18} aria-hidden="true" className={styles.spinner} />
          <span>Scanning… {elapsed} elapsed</span>
        </div>
        <p className={styles.liveNodes}>
          {state.liveNodeIds.length === 0
            ? "Watching the graph for new nodes as documents are processed."
            : `${state.liveNodeIds.length} new ${state.liveNodeIds.length === 1 ? "node has" : "nodes have"} arrived in the graph so far.`}
        </p>
      </Card>
    );
  }

  if (state.phase === "reconnect-required") {
    return (
      <ReconnectPrompt
        provider={state.provider}
        principal={state.principal}
        reason={state.message}
        onReconnect={onReconnect}
      />
    );
  }

  if (state.phase === "error") {
    return (
      <Card className={styles.card}>
        <div className={styles.errorBox} role="alert">
          <p className={styles.errorMessage}>{state.message}</p>
          {state.detail && <pre className={styles.errorDetail}>{state.detail}</pre>}
        </div>
      </Card>
    );
  }

  const { run, liveNodeIds } = state;
  const counts = computeStatusCounts(run.outcomes);
  const durationMs = Date.parse(run.finished_at) - Date.parse(run.started_at);
  const authFailures = run.connector_failures.filter((failure) => failure.is_auth_failure);
  const transientFailures = run.connector_failures.filter((failure) => !failure.is_auth_failure);

  return (
    <Card className={styles.card}>
      <div className={styles.header}>
        <div>
          <p className={styles.headerTitle}>
            {run.outcomes.length} {run.outcomes.length === 1 ? "document" : "documents"} seen,{" "}
            {run.new_node_ids.length} new {run.new_node_ids.length === 1 ? "node" : "nodes"} written
          </p>
          <p className={styles.headerMeta}>
            {run.sources_scanned.length > 0
              ? `Scanned ${run.sources_scanned.map(ingestionSourceLabel).join(", ")}. `
              : ""}
            {Number.isFinite(durationMs) && durationMs >= 0 ? `Took ${formatDuration(durationMs)}. ` : ""}
            Run {run.run_id}
          </p>
        </div>
        <ul className={styles.countChips}>
          {(Object.keys(counts) as (keyof typeof counts)[])
            .filter((status) => counts[status] > 0)
            .map((status) => (
              <li key={status} className={styles.countChip} data-status={status}>
                <span className={styles.countValue}>{counts[status]}</span>
                <span className={styles.countLabel}>{ingestionStatusLabel(status)}</span>
              </li>
            ))}
        </ul>
      </div>

      {liveNodeIds.length > 0 && (
        <p className={styles.liveNodes}>
          {liveNodeIds.length} {liveNodeIds.length === 1 ? "node" : "nodes"} arrived live in the graph during this
          scan.
        </p>
      )}

      {authFailures.length > 0 && (
        <div className={styles.failureSection}>
          {authFailures.map((failure) => (
            <ReconnectPrompt
              key={`${failure.source}:${failure.principal}`}
              provider={failure.source === "gmail" ? "google" : failure.source === "outlook" ? "microsoft" : null}
              principal={failure.principal}
              reason={`${ingestionSourceLabel(failure.source)} could not be scanned: ${failure.reason}`}
              onReconnect={onReconnect}
            />
          ))}
        </div>
      )}

      {transientFailures.length > 0 && (
        <div className={styles.failureSection} role="alert">
          <p className={styles.failureHeading}>Connector problems (not an authorisation issue)</p>
          <ul className={styles.plainList}>
            {transientFailures.map((failure) => (
              <li key={`${failure.source}:${failure.principal}`} className={styles.failureItem}>
                {ingestionSourceLabel(failure.source)} ({failure.principal}): {failure.reason}
              </li>
            ))}
          </ul>
        </div>
      )}

      {run.run_errors.length > 0 && (
        <div className={styles.failureSection} role="alert" data-testid="run-errors">
          <p className={styles.failureHeading}>
            Run-level problems: this result is only partially trustworthy
          </p>
          <ul className={styles.plainList}>
            {run.run_errors.map((err) => (
              <li key={err} className={styles.failureItem}>
                {err}
              </li>
            ))}
          </ul>
        </div>
      )}

      {run.outcomes.length > 0 ? (
        <ul className={styles.rows}>
          {run.outcomes.map((outcome) => (
            <OutcomeRow key={outcome.content_hash} outcome={outcome} />
          ))}
        </ul>
      ) : (
        run.connector_failures.length === 0 &&
        run.run_errors.length === 0 && (
          <p className={styles.idle}>No documents were found in the scanned window.</p>
        )
      )}
    </Card>
  );
}
