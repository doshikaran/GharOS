import { Badge } from "@/components/design-system/Badge";
import type { SalaryCalculationResult } from "@/lib/ledger";
import styles from "./SalaryFigureBreakdown.module.css";

export interface SalaryFigureBreakdownProps {
  readonly salary: SalaryCalculationResult;
}

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 }).format(amount);
}

/**
 * Renders every intermediate figure of a `SalaryCalculationResult` — days
 * worked, absent, and on unpaid leave; the daily rate; the gross amount;
 * every advance deducted (with its real `LedgerEvent` id, for audit); and
 * the final net figure — matching that type's own "auditable, not just the
 * final figure" design intent (`backend/app/solvers/salary_calculator.py`'s
 * own docstring). Never renders only the bottom-line number.
 */
export function SalaryFigureBreakdown({ salary }: SalaryFigureBreakdownProps) {
  return (
    <dl className={styles.breakdown}>
      <div className={styles.row}>
        <dt>Days worked</dt>
        <dd>{salary.daysWorked}</dd>
      </div>
      <div className={styles.row}>
        <dt>Days absent</dt>
        <dd>{salary.daysAbsent}</dd>
      </div>
      <div className={styles.row}>
        <dt>Days on unpaid leave</dt>
        <dd>{salary.daysOnLeaveUnpaid}</dd>
      </div>
      <div className={styles.row}>
        <dt>Daily rate</dt>
        <dd>{formatCurrency(salary.dailyRate, salary.currency)}</dd>
      </div>
      <div className={styles.row}>
        <dt>Gross amount</dt>
        <dd>{formatCurrency(salary.grossAmount, salary.currency)}</dd>
      </div>
      <div className={styles.row}>
        <dt>Advances deducted</dt>
        <dd>
          {formatCurrency(salary.totalAdvancesDeducted, salary.currency)}
          {salary.advanceEventIds.length > 0 && (
            <span className={styles.advanceIds}> ({salary.advanceEventIds.join(", ")})</span>
          )}
        </dd>
      </div>
      <div className={[styles.row, styles.netRow].join(" ")}>
        <dt>Net salary due</dt>
        <dd>
          <strong>{formatCurrency(salary.netSalaryDue, salary.currency)}</strong>
          {salary.flooredAtZero && (
            <Badge variant="warning" className={styles.flooredBadge}>
              Floored at zero — advances exceeded gross pay
            </Badge>
          )}
        </dd>
      </div>
    </dl>
  );
}
