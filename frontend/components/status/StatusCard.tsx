import { Badge, type BadgeVariant } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import type { CheckFailureKind, CheckOutcome, StatusCheckDefinition } from "@/lib/status-checks";
import styles from "./StatusCard.module.css";

export type StatusCardState = { status: "pending" } | CheckOutcome;

export interface StatusCardProps {
  definition: StatusCheckDefinition;
  state: StatusCardState;
}

const BADGE_VARIANT: Record<StatusCardState["status"], BadgeVariant> = {
  pending: "neutral",
  success: "success",
  failure: "danger",
};

const BADGE_LABEL: Record<StatusCardState["status"], string> = {
  pending: "Checking…",
  success: "Reachable",
  failure: "Failed",
};

const FAILURE_KIND_LABEL: Record<CheckFailureKind, string> = {
  network: "Network error",
  timeout: "Timed out",
  "http-error": "HTTP error response",
  "invalid-json": "Invalid response body",
};

/**
 * One check's result, rendered as a design-system `Card`. Always shows
 * which check ran, whether it succeeded, and the real response payload
 * or the real error detail — never a generic "something went wrong"
 * (CTO brief, requirement #3: failures must be visible, not swallowed).
 */
export function StatusCard({ definition, state }: StatusCardProps) {
  return (
    <Card
      className={styles.card}
      title={
        <span className={styles.titleRow}>
          {definition.label}
          <Badge variant={BADGE_VARIANT[state.status]}>{BADGE_LABEL[state.status]}</Badge>
        </span>
      }
    >
      <p className={styles.description}>{definition.description}</p>
      <p className={styles.endpoint}>
        {definition.method} {definition.path}
      </p>

      {state.status === "pending" && (
        <p className={styles.pending} role="status">
          Waiting for a response…
        </p>
      )}

      {state.status === "success" && (
        <div className={styles.result}>
          <p className={styles.meta}>
            HTTP {state.httpStatus} · {state.durationMs}ms
          </p>
          <pre className={styles.payload}>{JSON.stringify(state.data, null, 2)}</pre>
        </div>
      )}

      {state.status === "failure" && (
        <div className={styles.result} role="alert">
          <p className={styles.meta}>
            {FAILURE_KIND_LABEL[state.kind]}
            {state.httpStatus !== undefined ? ` · HTTP ${state.httpStatus}` : ""} ·{" "}
            {state.durationMs}ms
          </p>
          <p className={styles.errorMessage}>{state.message}</p>
          {state.body !== undefined && (
            <pre className={styles.payload}>
              {typeof state.body === "string" ? state.body : JSON.stringify(state.body, null, 2)}
            </pre>
          )}
        </div>
      )}
    </Card>
  );
}
