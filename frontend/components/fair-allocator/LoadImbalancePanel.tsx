import { Badge } from "@/components/design-system/Badge";
import type { BadgeVariant } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import type { LoadImbalanceFinding, LoadImbalanceVerdict } from "@/lib/fair-allocator";
import styles from "./LoadImbalancePanel.module.css";

export interface LoadImbalancePanelProps {
  readonly findings: readonly LoadImbalanceFinding[];
  readonly personName: (personId: string) => string;
}

const VERDICT_LABEL: Record<LoadImbalanceVerdict, string> = {
  balanced: "Balanced",
  creeping_imbalance: "Creeping imbalance",
  insufficient_data: "Insufficient data",
};

const VERDICT_VARIANT: Record<LoadImbalanceVerdict, BadgeVariant> = {
  balanced: "success",
  creeping_imbalance: "warning",
  insufficient_data: "neutral",
};

function formatPercent(share: number | null): string {
  if (share === null) return "—";
  return `${Math.round(share * 100)}%`;
}

function formatDrift(drift: number | null): string {
  if (drift === null) return "—";
  const sign = drift > 0 ? "+" : "";
  return `${sign}${Math.round(drift * 100)} pts`;
}

/**
 * A real, browsable rendering of every `LoadImbalanceFinding` (A21) —
 * expected share vs. observed share with the evidence behind the verdict,
 * never just a verdict label on its own (PHASES.md Phase 8, E4 work item 5).
 */
export function LoadImbalancePanel({ findings, personName }: LoadImbalancePanelProps) {
  if (findings.length === 0) {
    return <p className={styles.emptyState}>No load-imbalance findings yet.</p>;
  }

  return (
    <div className={styles.grid}>
      {findings.map((finding) => (
        <Card key={finding.personId} title={personName(finding.personId)} className={styles.card}>
          <div className={styles.verdictRow}>
            <Badge variant={VERDICT_VARIANT[finding.verdict]}>{VERDICT_LABEL[finding.verdict]}</Badge>
            <span className={styles.modelTier}>
              {finding.modelTier === "flash" ? "Narrated by a real model call" : "Deterministic — no model call needed"}
            </span>
          </div>

          <dl className={styles.figures}>
            <div>
              <dt>Expected share</dt>
              <dd>{formatPercent(finding.expectedShare)}</dd>
            </div>
            <div>
              <dt>Observed share</dt>
              <dd>{formatPercent(finding.observedShare)}</dd>
            </div>
            <div>
              <dt>Drift</dt>
              <dd className={(finding.drift ?? 0) > 0 ? styles.driftPositive : styles.driftNegative}>
                {formatDrift(finding.drift)}
              </dd>
            </div>
          </dl>

          <p className={styles.reasoning}>{finding.reasoning}</p>

          <div className={styles.confidenceRow}>
            <span className={styles.confidenceLabel}>Confidence</span>
            <span className={styles.confidenceValue}>{Math.round(finding.confidence * 100)}%</span>
          </div>
        </Card>
      ))}
    </div>
  );
}
