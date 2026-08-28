import { Badge } from "@/components/design-system/Badge";
import type { RiskCategory, RiskRegisterEntry } from "@/lib/simulator";
import styles from "./RiskRegister.module.css";

export interface RiskRegisterProps {
  readonly entries: readonly RiskRegisterEntry[];
}

const CATEGORY_BADGE_VARIANT: Record<RiskCategory, "danger" | "warning"> = {
  "over-optimistic claim": "danger",
  "omitted second-order effect": "warning",
};

/**
 * A flat, scannable list derived from every branch's critique (this
 * phase's brief: "risk register: derived from the critiques across all
 * branches"). Every row names its branch and category up front — nothing
 * here should require flipping back to a specific `BranchCard` to
 * understand.
 */
export function RiskRegister({ entries }: RiskRegisterProps) {
  if (entries.length === 0) {
    return <p className={styles.empty}>No risks raised across any branch&apos;s critique.</p>;
  }

  return (
    <ul className={styles.list} aria-label="Risk register">
      {entries.map((entry, index) => (
        <li key={`${entry.branchId}-${entry.category}-${index}`} className={styles.row}>
          <div className={styles.meta}>
            <span className={styles.branchLabel}>{entry.branchLabel}</span>
            <Badge variant={CATEGORY_BADGE_VARIANT[entry.category]}>{entry.category}</Badge>
          </div>
          <p className={styles.text}>{entry.text}</p>
        </li>
      ))}
    </ul>
  );
}
