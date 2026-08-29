import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import type { PayrollResult } from "@/lib/ledger";
import { RegisterImagePanel } from "./RegisterImagePanel";
import { SalaryFigureBreakdown } from "./SalaryFigureBreakdown";
import styles from "./PayrollReview.module.css";

export interface PayrollResultCardProps {
  readonly result: PayrollResult;
  readonly baseUrl: string;
}

/**
 * One `PayrollResult` — the register image beside the computed figure
 * (spec's exact wording, §10.7's demo beat), every intermediate salary
 * figure visible, not just the net number. When `needsHumanReview` is
 * true, this renders visually distinct and unmissable — Gate 7's literal
 * checklist item "low confidence -> shows image", made visible.
 */
export function PayrollResultCard({ result, baseUrl }: PayrollResultCardProps) {
  return (
    <Card
      className={[styles.card, result.needsHumanReview && styles.needsReviewCard].filter(Boolean).join(" ")}
      title={
        <span className={styles.titleRow}>
          <span>{result.month} payroll</span>
          {result.needsHumanReview && <Badge variant="danger">Needs human review</Badge>}
          {!result.needsHumanReview && <Badge variant="success">No review needed</Badge>}
        </span>
      }
    >
      <div className={styles.body}>
        {result.needsHumanReview && (
          <div className={styles.reviewBanner} role="alert">
            <p className={styles.reviewReason}>{result.reviewReason}</p>
            {result.unresolvedMarks.length > 0 && (
              <ul className={styles.unresolvedList}>
                {result.unresolvedMarks.map((mark) => (
                  <li key={mark.day}>
                    Day {mark.day}: {mark.reason}
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}

        <div className={styles.pane}>
          <RegisterImagePanel
            key={result.registerImageRef ?? result.month}
            baseUrl={baseUrl}
            registerImageRef={result.registerImageRef}
            month={result.month}
          />
          <div className={styles.figureColumn}>
            {result.salary ? (
              <SalaryFigureBreakdown salary={result.salary} />
            ) : (
              <p className={styles.noFigure}>
                No computed salary figure yet, this is held pending human review of the flagged day(s), never a
                guessed number.
              </p>
            )}
          </div>
        </div>

        <p className={styles.reasoning}>{result.reasoning}</p>
      </div>
    </Card>
  );
}

export interface PayrollReviewProps {
  readonly results: readonly PayrollResult[];
  readonly baseUrl: string;
}

/** A real, browsable list of every `PayrollResult` (PHASES.md Phase 7, E4
 * work item 4 — the payroll review). */
export function PayrollReview({ results, baseUrl }: PayrollReviewProps) {
  if (results.length === 0) {
    return <p className={styles.emptyState}>No payroll cycles computed yet.</p>;
  }

  return (
    <div className={styles.surface}>
      {results.map((result) => (
        <PayrollResultCard key={`${result.staffPersonId}-${result.month}`} result={result} baseUrl={baseUrl} />
      ))}
    </div>
  );
}
