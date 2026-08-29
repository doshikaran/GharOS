"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { subscribeToGraphStream } from "@/lib/graph-stream";
import {
  DEMO_HOUSEHOLD_ID,
  disconnectConnection,
  fetchConnections,
  ingestionSourceLabel,
  newIdempotencyScope,
  oauthStartUrl,
  providerScanKinds,
  startDriveIngest,
  startScan,
  uploadFilesForIngest,
  wireFailureLabel,
  type ConnectionRecord,
  type IngestMeta,
  type IngestSubmitResult,
  type IngestionRunResult,
  type IngestionSourceKind,
  type OAuthProvider,
} from "@/lib/connections";
import { PRIYA_ID } from "@/lib/fair-allocator";
import { ConnectionList } from "./ConnectionList";
import { DrivePickerButton } from "./DrivePickerButton";
import { IngestionRunView, type IngestionRunViewState } from "./IngestionRunView";
import { SCAN_WINDOW_SECONDS, ScanControl } from "./ScanControl";
import { UploadDropzone } from "./UploadDropzone";
import styles from "./ConnectionsExplorer.module.css";

export interface ConnectionsExplorerProps {
  readonly baseUrl: string;
}

type LoadState =
  | { readonly status: "loading" }
  | { readonly status: "error"; readonly message: string; readonly detail?: string }
  | { readonly status: "ready" };

type RunPhase =
  | { readonly kind: "idle" }
  | { readonly kind: "running"; readonly startedAtMs: number }
  | { readonly kind: "done"; readonly run: IngestionRunResult }
  | {
      readonly kind: "reconnect";
      readonly provider: OAuthProvider | null;
      readonly principal: string | null;
      readonly message: string;
    }
  | { readonly kind: "error"; readonly message: string; readonly detail?: string };

/**
 * Top-level stateful orchestrator for `/connections` (PHASES.md Phase
 * 14.5) — a client component kept separate from the page's Server
 * Component (same split as `GraphExplorer` / `LedgerExplorer`).
 *
 * Real, live data throughout: `GET /connections` on mount, `POST
 * /connections/{provider}/{principal}/disconnect` for disconnect (with
 * optimistic UI then refetch), and the one `POST /ingest` wire for the
 * scan / upload / Drive-picker paths. While a run is in flight it
 * subscribes to the existing `/graph/stream` so newly written nodes are
 * counted live here too (no new endpoint — Phase 14.5 E4 brief).
 */
export function ConnectionsExplorer({ baseUrl }: ConnectionsExplorerProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [connections, setConnections] = useState<readonly ConnectionRecord[]>([]);
  const [triggeredBy, setTriggeredBy] = useState<string>(PRIYA_ID);
  const [runPhase, setRunPhase] = useState<RunPhase>({ kind: "idle" });
  const [liveNodeIds, setLiveNodeIds] = useState<readonly string[]>([]);
  const [disconnectingKeys, setDisconnectingKeys] = useState<ReadonlySet<string>>(new Set());
  const [actionError, setActionError] = useState<string | null>(null);

  const submitting = runPhase.kind === "running";
  const inFlightRef = useRef(false);

  const loadConnections = useCallback(async () => {
    const result = await fetchConnections(baseUrl);
    if (result.ok) {
      setConnections(result.data);
      setLoadState({ status: "ready" });
    } else {
      setLoadState({
        status: "error",
        message: `${wireFailureLabel(result.kind)}: ${result.message}`,
        detail: result.body,
      });
    }
  }, [baseUrl]);

  useEffect(() => {
    let cancelled = false;
    void fetchConnections(baseUrl).then((result) => {
      if (cancelled) return;
      if (result.ok) {
        setConnections(result.data);
        setLoadState({ status: "ready" });
      } else {
        setLoadState({
          status: "error",
          message: `${wireFailureLabel(result.kind)}: ${result.message}`,
          detail: result.body,
        });
      }
    });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  // Live graph growth while a run is in flight — the same `/graph/stream`
  // the graph view uses, no new lib, no new endpoint.
  useEffect(() => {
    if (runPhase.kind !== "running") return undefined;
    const unsubscribe = subscribeToGraphStream(baseUrl, {
      onEvent: (event) => {
        if (event.kind !== "node") return;
        setLiveNodeIds((prev) => (prev.includes(event.node.id) ? prev : [...prev, event.node.id]));
      },
      onError: () => {
        /* a stream hiccup never invalidates the run result itself */
      },
    });
    return unsubscribe;
  }, [runPhase.kind, baseUrl]);

  const activeConnections = useMemo(
    () => connections.filter((record) => record.revoked_at === null),
    [connections],
  );

  const scanSources = useMemo<readonly IngestionSourceKind[]>(() => {
    const kinds = new Set<IngestionSourceKind>();
    for (const record of activeConnections) {
      for (const kind of providerScanKinds(record.provider)) kinds.add(kind);
    }
    return [...kinds];
  }, [activeConnections]);

  const scanPrincipal = useMemo<string | null>(() => {
    const google = activeConnections.find((record) => record.provider === "google");
    const microsoft = activeConnections.find((record) => record.provider === "microsoft");
    return google?.principal ?? microsoft?.principal ?? null;
  }, [activeConnections]);

  const googlePrincipal = useMemo<string | null>(
    () => activeConnections.find((record) => record.provider === "google")?.principal ?? null,
    [activeConnections],
  );

  const runViewState = useMemo<IngestionRunViewState>(() => {
    switch (runPhase.kind) {
      case "idle":
        return { phase: "idle" };
      case "running":
        return { phase: "running", startedAtMs: runPhase.startedAtMs, liveNodeIds };
      case "done":
        return { phase: "done", run: runPhase.run, liveNodeIds };
      case "reconnect":
        return {
          phase: "reconnect-required",
          provider: runPhase.provider,
          principal: runPhase.principal,
          message: runPhase.message,
        };
      case "error":
        return { phase: "error", message: runPhase.message, detail: runPhase.detail };
    }
  }, [runPhase, liveNodeIds]);

  const buildMeta = useCallback(
    (prefix: string): IngestMeta => ({
      idempotencyScope: newIdempotencyScope(prefix),
      triggeredBy,
      householdId: DEMO_HOUSEHOLD_ID,
    }),
    [triggeredBy],
  );

  const runIngest = useCallback(
    async (submit: () => Promise<IngestSubmitResult>) => {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
      setLiveNodeIds([]);
      setRunPhase({ kind: "running", startedAtMs: Date.now() });
      try {
        const result = await submit();
        if (result.status === "ok") {
          setRunPhase({ kind: "done", run: result.run });
        } else if (result.status === "reconnect-required") {
          setRunPhase({
            kind: "reconnect",
            provider: result.provider,
            principal: result.principal,
            message: result.message,
          });
        } else {
          setRunPhase({
            kind: "error",
            message: `${wireFailureLabel(result.kind)}: ${result.message}`,
            detail: result.body,
          });
        }
      } finally {
        inFlightRef.current = false;
      }
      await loadConnections();
    },
    [loadConnections],
  );

  const handleScan = useCallback(() => {
    if (scanSources.length === 0 || scanPrincipal === null) return;
    void runIngest(() =>
      startScan(baseUrl, {
        sources: scanSources,
        windowSeconds: SCAN_WINDOW_SECONDS,
        principal: scanPrincipal,
        meta: buildMeta("manual-scan"),
      }),
    );
  }, [baseUrl, buildMeta, runIngest, scanPrincipal, scanSources]);

  const handleUpload = useCallback(
    (files: readonly File[]) => {
      void runIngest(() => uploadFilesForIngest(baseUrl, files, buildMeta("upload")));
    },
    [baseUrl, buildMeta, runIngest],
  );

  const handleDrivePicked = useCallback(
    (driveFileIds: readonly string[]) => {
      void runIngest(() => startDriveIngest(baseUrl, driveFileIds, buildMeta("drive-pick")));
    },
    [baseUrl, buildMeta, runIngest],
  );

  const handleReconnect = useCallback(
    (provider: OAuthProvider) => {
      window.location.assign(oauthStartUrl(baseUrl, provider));
    },
    [baseUrl],
  );

  const handleDisconnect = useCallback(
    async (provider: OAuthProvider, principal: string) => {
      const key = `${provider}:${principal}`;
      setActionError(null);
      setDisconnectingKeys((prev) => new Set(prev).add(key));
      // Optimistic: mark the record revoked locally straight away.
      setConnections((prev) =>
        prev.map((record) =>
          record.provider === provider && record.principal === principal && record.revoked_at === null
            ? { ...record, revoked_at: new Date().toISOString() }
            : record,
        ),
      );
      const result = await disconnectConnection(baseUrl, provider, principal);
      if (!result.ok) {
        setActionError(
          `Could not disconnect ${ingestionSourceLabel(provider === "google" ? "gmail" : "outlook")}: ${result.message}`,
        );
      }
      setDisconnectingKeys((prev) => {
        const next = new Set(prev);
        next.delete(key);
        return next;
      });
      await loadConnections();
    },
    [baseUrl, loadConnections],
  );

  if (loadState.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading your connected accounts…
      </p>
    );
  }

  if (loadState.status === "error") {
    return (
      <div className={styles.status} role="alert">
        <p className={styles.errorMessage}>Could not load your connected accounts. {loadState.message}</p>
        {loadState.detail && <pre className={styles.errorDetail}>{loadState.detail}</pre>}
      </div>
    );
  }

  return (
    <div className={styles.explorer}>
      {actionError && (
        <p className={styles.actionError} role="alert">
          {actionError}
        </p>
      )}

      <section aria-label="Connected accounts">
        <h2 className={styles.sectionHeading}>Connected accounts</h2>
        <ConnectionList
          connections={connections}
          baseUrl={baseUrl}
          onDisconnect={handleDisconnect}
          disconnectingKeys={disconnectingKeys}
        />
      </section>

      <section aria-label="Scan connected mail">
        <h2 className={styles.sectionHeading}>Scan connected mail</h2>
        <ScanControl
          sources={scanSources}
          principal={scanPrincipal}
          triggeredBy={triggeredBy}
          onTriggeredByChange={setTriggeredBy}
          onScan={handleScan}
          running={submitting}
        />
      </section>

      <section aria-label="Add files">
        <h2 className={styles.sectionHeading}>Add files</h2>
        <div className={styles.fileRow}>
          <UploadDropzone onFiles={handleUpload} running={submitting} />
          <div className={styles.driveColumn}>
            <p className={styles.driveHeading}>From Google Drive</p>
            <DrivePickerButton
              baseUrl={baseUrl}
              googlePrincipal={googlePrincipal}
              onPicked={handleDrivePicked}
              running={submitting}
            />
          </div>
        </div>
      </section>

      <section aria-label="Ingestion run">
        <h2 className={styles.sectionHeading}>Latest run</h2>
        <IngestionRunView state={runViewState} onReconnect={handleReconnect} />
      </section>
    </div>
  );
}
