import { Card } from "@/components/design-system/Card";
import type { RecoveredMoneySummary } from "@/lib/ledger";
import styles from "./RecoveredMoneyCounter.module.css";

export interface RecoveredMoneyCounterProps {
  readonly summary: RecoveredMoneySummary;
}

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
  }).format(amount);
}

/**
 * The spec §10.7 demo metric, verbatim in structure: "found ₹X/year of
 * leakage — three claims drafted, awaiting approval." Every number here
 * comes from `computeRecoveredMoneySummary`'s real arithmetic over the
 * household's actual `LeakageCase` data — never a fixed display string.
 */
export function RecoveredMoneyCounter({ summary }: RecoveredMoneyCounterProps) {
  return (
    <Card className={styles.card} title="Recovered-money counter">
      <p className={styles.headline} role="status" aria-live="polite">
        Found <strong className={styles.amount}>{formatCurrency(summary.annualLeakageTotal, summary.currency)}/year</strong> of
        leakage — <strong>{summary.draftsAwaitingApproval}</strong> claim
        {summary.draftsAwaitingApproval === 1 ? "" : "s"} drafted, awaiting approval.
      </p>
      <p className={styles.detail}>
        {summary.leakageCaseCount} recurring commitment{summary.leakageCaseCount === 1 ? "" : "s"} flagged as leakage
        this pass — computed from each commitment&apos;s real cadence and amount (the full annual amount for a
        cancellation, only the unexplained hike for a kept service being challenged on price).
      </p>
    </Card>
  );
}
