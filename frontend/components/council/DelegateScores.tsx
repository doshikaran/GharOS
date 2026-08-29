import { Badge } from "@/components/design-system/Badge";
import { branchLabel, personLabel, type DelegateScoring } from "@/lib/council";
import styles from "./DelegateScores.module.css";

export interface DelegateScoresProps {
  readonly delegateScorings: readonly DelegateScoring[];
}

/**
 * Every convened member's own cost for each surviving option — one card
 * per person, each visibly attributed by name (this phase's brief:
 * "visibly attributed to that person, never anonymized into a single
 * aggregate number"). Costs are only ever comparable *within* one
 * person's own row (ADR-019 Decision 3) — rendered as a per-person
 * ranking, never summed or averaged across rows into a household total.
 */
export function DelegateScores({ delegateScorings }: DelegateScoresProps) {
  return (
    <ul className={styles.list} aria-label="Delegate scores">
      {delegateScorings.map((scoring) => {
        const ranked = Object.entries(scoring.valuationProfile.costs).sort(([, a], [, b]) => a - b);
        const topPickBranchId = ranked[0]?.[0];

        return (
          <li key={scoring.personId} className={styles.card}>
            <div className={styles.header}>
              <p className={styles.personName}>{personLabel(scoring.personId)}</p>
              <Badge variant="royal">{scoring.valuationProfile.elicitationMethod.replace(/_/g, " ")}</Badge>
            </div>

            <table className={styles.table}>
              <caption className={styles.caption}>
                {personLabel(scoring.personId)}&apos;s own cost per option — lower is more preferred, only ever
                compared against their own other rows, never against another person&apos;s numbers.
              </caption>
              <thead>
                <tr>
                  <th scope="col">Option</th>
                  <th scope="col">Cost</th>
                </tr>
              </thead>
              <tbody>
                {ranked.map(([branchId, cost]) => (
                  <tr key={branchId} data-top-pick={branchId === topPickBranchId}>
                    <td>{branchLabel(branchId)}</td>
                    <td>
                      {cost.toFixed(1)}
                      {branchId === topPickBranchId && <span className={styles.topPickTag}> — own top pick</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>

            <p className={styles.reasoning}>{scoring.reasoning}</p>
          </li>
        );
      })}
    </ul>
  );
}
