"use client";

import { useEffect, useMemo, useState } from "react";
import { ApprovalsBoard } from "@/components/approvals/ApprovalsBoard";
import type { ApprovalQueueItem } from "@/lib/approvals";
import { fetchGraphSnapshot, GraphApiError } from "@/lib/graph-api";
import type { GraphEdge, GraphNode } from "@/lib/graph-types";
import {
  buildLedgerView,
  filterTransactions,
  type LedgerCommitmentRow,
  type LedgerEventKind,
  type LedgerTransactionFilters,
} from "@/lib/ledger-transactions";
import { computeRecoveredMoneySummary, getDisputePresentations, getLeakageCases, getPayrollResults } from "@/lib/ledger";
import { buildMandateCancelApprovalItem, MANDATE_CANCEL_ID_PREFIX } from "@/lib/mandate-cancel";
import { DisputeSurface } from "./DisputeSurface";
import { LeakageRecoverySurface } from "./LeakageRecoverySurface";
import { LedgerTransactionTable } from "./LedgerTransactionTable";
import { PayrollReview } from "./PayrollReview";
import { RecoveredMoneyCounter } from "./RecoveredMoneyCounter";
import styles from "./LedgerExplorer.module.css";

export interface LedgerExplorerProps {
  readonly baseUrl: string;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

/**
 * Top-level stateful orchestrator for `/ledger` (PHASES.md Phase 7) — a
 * client component kept separate from `app/ledger/page.tsx`, which stays a
 * Server Component so it can export page `metadata` (same split as
 * `GraphExplorer`/`ApprovalsBoard`).
 *
 * The transaction list and recurring-commitment list are real, live data
 * fetched from `/graph/snapshot` — the same endpoint `GraphExplorer` uses.
 * The leakage/recovery, dispute, and payroll surfaces are fixture-backed
 * (see `lib/ledger.ts`'s module docstring for why). The mandate-cancel
 * demo flow bridges the two: a live commitment, proposed for cancellation
 * by a real user action here, routed through the exact same
 * `ApprovalsBoard` Phase 5 built.
 */
export function LedgerExplorer({ baseUrl }: LedgerExplorerProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [nodes, setNodes] = useState<readonly GraphNode[]>([]);
  const [edges, setEdges] = useState<readonly GraphEdge[]>([]);
  const [kindFilter, setKindFilter] = useState<readonly LedgerEventKind[] | null>(null);
  const [commitmentFilter, setCommitmentFilter] = useState<string | null>(null);
  const [mandateCancelItems, setMandateCancelItems] = useState<ApprovalQueueItem[]>([]);

  useEffect(() => {
    let cancelled = false;
    fetchGraphSnapshot(baseUrl)
      .then((snapshot) => {
        if (cancelled) return;
        setNodes(snapshot.nodes);
        setEdges(snapshot.edges);
        setLoadState({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message = err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load the ledger.";
        setLoadState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  const ledgerView = useMemo(() => buildLedgerView(nodes, edges), [nodes, edges]);
  const filters: LedgerTransactionFilters = useMemo(
    () => ({ kinds: kindFilter, commitmentId: commitmentFilter }),
    [kindFilter, commitmentFilter],
  );
  const visibleTransactions = useMemo(
    () => filterTransactions(ledgerView.transactions, filters),
    [ledgerView, filters],
  );

  const leakageCases = useMemo(() => getLeakageCases(), []);
  const disputes = useMemo(() => getDisputePresentations(), []);
  const payrollResults = useMemo(() => getPayrollResults(), []);
  const recoveredMoney = useMemo(() => computeRecoveredMoneySummary(leakageCases), [leakageCases]);

  const proposedMandateCancelIds = useMemo(
    () =>
      new Set(
        mandateCancelItems.map((item) => item.id.slice(MANDATE_CANCEL_ID_PREFIX.length)),
      ),
    [mandateCancelItems],
  );

  function handleProposeMandateCancel(commitment: LedgerCommitmentRow) {
    setMandateCancelItems((prev) => {
      const item = buildMandateCancelApprovalItem(commitment);
      if (prev.some((existing) => existing.id === item.id)) return prev;
      return [...prev, item];
    });
  }

  if (loadState.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading the household ledger…
      </p>
    );
  }

  if (loadState.status === "error") {
    return (
      <p className={styles.status} role="alert">
        Could not load the ledger: {loadState.message}
      </p>
    );
  }

  return (
    <div className={styles.explorer}>
      <RecoveredMoneyCounter summary={recoveredMoney} />

      <section aria-label="Transactions and recurring commitments">
        <h2 className={styles.sectionHeading}>Transactions &amp; recurring commitments</h2>
        <LedgerTransactionTable
          transactions={visibleTransactions}
          allTransactionCount={ledgerView.transactions.length}
          commitments={ledgerView.commitments}
          kindFilter={kindFilter}
          onKindFilterChange={setKindFilter}
          commitmentFilter={commitmentFilter}
          onCommitmentFilterChange={setCommitmentFilter}
          onProposeMandateCancel={handleProposeMandateCancel}
          proposedMandateCancelIds={proposedMandateCancelIds}
        />
      </section>

      {mandateCancelItems.length > 0 && (
        <section aria-label="Mandate cancellation approval gate">
          <h2 className={styles.sectionHeading}>Mandate cancellation — approval gate</h2>
          <p className={styles.sectionIntro}>
            Cancelling a live mandate routes through the exact same Approval Gate every payment or mandate action
            does — nothing here executes until a household member explicitly confirms it below.
          </p>
          <ApprovalsBoard initialItems={[]} extraItems={mandateCancelItems} />
        </section>
      )}

      <section aria-label="Leakage and recovery">
        <h2 className={styles.sectionHeading}>Leakage &amp; recovery</h2>
        <LeakageRecoverySurface cases={leakageCases} />
      </section>

      <section aria-label="Disputes">
        <h2 className={styles.sectionHeading}>Disputes</h2>
        <DisputeSurface disputes={disputes} />
      </section>

      <section aria-label="Payroll review">
        <h2 className={styles.sectionHeading}>Payroll review</h2>
        <PayrollReview results={payrollResults} baseUrl={baseUrl} />
      </section>
    </div>
  );
}
