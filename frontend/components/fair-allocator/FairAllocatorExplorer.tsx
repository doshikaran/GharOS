"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchGraphSnapshot, GraphApiError } from "@/lib/graph-api";
import type { GraphNode } from "@/lib/graph-types";
import { buildLiveCostMatrix } from "@/lib/fair-allocator-matrix";
import {
  getComparativePreferences,
  getEf1Violations,
  getFairAllocationResult,
  getFairnessVerificationResult,
  getLoadImbalanceFindings,
} from "@/lib/fair-allocator";
import { AllocationResult } from "./AllocationResult";
import { CostMatrix } from "./CostMatrix";
import { LoadImbalancePanel } from "./LoadImbalancePanel";
import { PersonShareExplanations } from "./PersonShareExplanations";
import { RenegotiationDemo } from "./RenegotiationDemo";
import styles from "./FairAllocatorExplorer.module.css";

export interface FairAllocatorExplorerProps {
  readonly baseUrl: string;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

/**
 * Top-level stateful orchestrator for `/fair-allocator` (PHASES.md Phase 8)
 * — a client component kept separate from `app/fair-allocator/page.tsx`,
 * which stays a Server Component so it can export page `metadata` (same
 * split as `LedgerExplorer`/`GraphExplorer`).
 *
 * The cost matrix (people × real, current obligations) is real, live data
 * fetched from `/graph/snapshot` — the same endpoint every prior phase's
 * explorer uses. The solved allocation, EF1 verification, per-person
 * explanations, renegotiation demo, and load-imbalance findings are
 * fixture-backed (see `lib/fair-allocator.ts`'s module docstring for why,
 * and for the hand-checked arithmetic tying them back to this matrix's own
 * live numbers).
 */
export function FairAllocatorExplorer({ baseUrl }: FairAllocatorExplorerProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [nodes, setNodes] = useState<readonly GraphNode[]>([]);
  const [matrixConfirmed, setMatrixConfirmed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchGraphSnapshot(baseUrl)
      .then((snapshot) => {
        if (cancelled) return;
        setNodes(snapshot.nodes);
        setLoadState({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load the cost matrix.";
        setLoadState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  const matrix = useMemo(() => buildLiveCostMatrix(nodes), [nodes]);

  const taskTitleLookup = useMemo(() => {
    const fromMatrix = new Map(matrix.tasks.map((task) => [task.taskId, task.title]));
    return (taskId: string) => fromMatrix.get(taskId) ?? taskId;
  }, [matrix]);

  const personNameLookup = useMemo(() => {
    const fromMatrix = new Map(matrix.people.map((person) => [person.personId, person.displayName]));
    return (personId: string) => fromMatrix.get(personId) ?? personId;
  }, [matrix]);

  const comparativePreferences = useMemo(() => getComparativePreferences(), []);
  const beforeAllocation = useMemo(() => getFairAllocationResult("before"), []);
  const beforeViolations = useMemo(() => getEf1Violations("before"), []);
  const beforeVerification = useMemo(() => getFairnessVerificationResult("before"), []);
  const loadImbalanceFindings = useMemo(() => getLoadImbalanceFindings(), []);

  if (loadState.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading the household&apos;s cost matrix…
      </p>
    );
  }

  if (loadState.status === "error") {
    return (
      <p className={styles.status} role="alert">
        Could not load the cost matrix: {loadState.message}
      </p>
    );
  }

  return (
    <div className={styles.explorer}>
      <section aria-label="Cost matrix">
        <h2 className={styles.sectionHeading}>Cost matrix</h2>
        <p className={styles.sectionIntro}>
          Every current household member and every current obligation, with each person&apos;s real, live stated
          cost where one exists. A dash means that person has never been asked, never a hidden zero.
        </p>
        <CostMatrix matrix={matrix} confirmed={matrixConfirmed} onConfirm={() => setMatrixConfirmed(true)} />
      </section>

      <section aria-label="This cycle's scope">
        <h2 className={styles.sectionHeading}>This cycle&apos;s allocation</h2>
        <p className={styles.sectionIntro}>
          The school pickup and Maya&apos;s salary payment go to Priya directly, she is the household&apos;s only
          driver and its only bank-account holder. The extended maintenance payment goes to Dadi directly for the
          same reason. None of the three has a second capability-eligible, priced person, so there is no contest to
          solve. The three remaining flexible errands, renewing Dadi&apos;s prescription, the pharmacy pickup, and
          the weekly grocery run, are the ones Priya and Maya actually share day to day, so that is where the fair
          allocator runs below.
        </p>

        {comparativePreferences.length > 0 && (
          <details className={styles.interviewEvidence}>
            <summary>Interview evidence behind this cycle&apos;s cost ordering ({comparativePreferences.length})</summary>
            <ul className={styles.preferenceList}>
              {comparativePreferences.map((pref, index) => (
                <li key={index}>
                  <strong>{personNameLookup(pref.personId)}:</strong> &ldquo;{pref.rawAnswerText}&rdquo;
                </li>
              ))}
            </ul>
          </details>
        )}

        {!matrixConfirmed ? (
          <p className={styles.gatedNote} role="status">
            Confirm the cost matrix above before this cycle&apos;s allocation is shown, a human must see and confirm
            the matrix before the fairness solver runs on it.
          </p>
        ) : (
          <>
            <AllocationResult
              result={beforeAllocation}
              violations={beforeViolations}
              taskTitle={taskTitleLookup}
              personName={personNameLookup}
            />

            <h2 className={styles.sectionHeading}>Per-person fairness explanations</h2>
            <PersonShareExplanations
              explanations={beforeVerification.explanations}
              personName={personNameLookup}
              taskTitle={taskTitleLookup}
            />

            <h2 className={styles.sectionHeading}>Renegotiation</h2>
            <RenegotiationDemo taskTitle={taskTitleLookup} personName={personNameLookup} />
          </>
        )}
      </section>

      <section aria-label="Load imbalance">
        <h2 className={styles.sectionHeading}>Load imbalance</h2>
        <p className={styles.sectionIntro}>
          Expected share of this cycle&apos;s total task cost against each person&apos;s real observed obligation
          load over the past 30 days.
        </p>
        <LoadImbalancePanel findings={loadImbalanceFindings} personName={personNameLookup} />
      </section>
    </div>
  );
}
