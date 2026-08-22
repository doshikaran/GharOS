"use client";

import { useEffect, useMemo, useState } from "react";
import { getApiBaseUrl } from "@/lib/api-base-url";
import { runStatusCheck, STATUS_CHECKS, type CheckId } from "@/lib/status-checks";
import { StatusCard, type StatusCardState } from "./StatusCard";
import styles from "./StatusBoard.module.css";

type ResultsById = Record<CheckId, StatusCardState>;

function buildInitialResults(): ResultsById {
  return Object.fromEntries(
    STATUS_CHECKS.map((definition) => [definition.id, { status: "pending" } as const]),
  ) as ResultsById;
}

function summarize(results: ResultsById): string {
  const values = Object.values(results);
  if (values.some((result) => result.status === "pending")) {
    return "Checking stack connectivity…";
  }
  const failed = values.filter((result) => result.status === "failure").length;
  if (failed === 0) {
    return `All ${values.length} checks reached the deployed backend successfully.`;
  }
  return `${failed} of ${values.length} checks failed to reach the deployed backend.`;
}

/**
 * Runs every check in `STATUS_CHECKS` against the configured API base URL
 * on mount and renders one `StatusCard` per check as results arrive.
 *
 * A client component (fetch + state) deliberately kept separate from
 * `app/status/page.tsx`, which stays a Server Component so it can export
 * page `metadata` — Next.js App Router does not allow a `"use client"`
 * file to also export `metadata`.
 */
export function StatusBoard() {
  const baseUrl = useMemo(() => getApiBaseUrl(), []);
  const [results, setResults] = useState<ResultsById>(buildInitialResults);

  useEffect(() => {
    let cancelled = false;

    STATUS_CHECKS.forEach((definition) => {
      runStatusCheck(definition, baseUrl)
        .then((outcome) => {
          if (!cancelled) {
            setResults((previous) => ({ ...previous, [definition.id]: outcome }));
          }
        })
        .catch((error: unknown) => {
          // runStatusCheck itself never rejects — every real failure path is
          // caught and returned as a typed CheckFailure. This branch only
          // guards against a genuinely unexpected bug in that contract, so
          // it still renders as a visible failed card rather than being
          // swallowed (gharos-standards: no swallowed exceptions).
          if (!cancelled) {
            const message = error instanceof Error ? error.message : String(error);
            setResults((previous) => ({
              ...previous,
              [definition.id]: {
                status: "failure",
                kind: "network",
                message: `Unexpected error running this check: ${message}`,
                durationMs: 0,
              },
            }));
          }
        });
    });

    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  return (
    <div className={styles.board}>
      <p className={styles.baseUrl}>
        Backend base URL: <code>{baseUrl}</code>
      </p>
      <p className={styles.summary} role="status" aria-live="polite">
        {summarize(results)}
      </p>
      <div className={styles.grid}>
        {STATUS_CHECKS.map((definition) => (
          <StatusCard key={definition.id} definition={definition} state={results[definition.id]} />
        ))}
      </div>
    </div>
  );
}
