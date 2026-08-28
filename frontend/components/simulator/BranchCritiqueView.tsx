import type { BranchCritique } from "@/lib/simulator";
import styles from "./BranchCritiqueView.module.css";

export interface BranchCritiqueViewProps {
  readonly critique: BranchCritique | undefined;
}

/**
 * A38 Consistency Critic's output for one branch — deliberately styled
 * apart from `BranchProjection`'s own rendering (a distinct bordered block
 * in `--edge-conflict`, the same "the critic actually pushed back" colour
 * register the graph uses for conflict edges) so a viewer can see the
 * critique pushed back on the projection above it, rather than reading as
 * more of the same claim blended in (this phase's brief).
 */
export function BranchCritiqueView({ critique }: BranchCritiqueViewProps) {
  if (!critique) {
    return null;
  }

  return (
    <div className={styles.wrapper} aria-label="Consistency critique">
      <p className={styles.heading}>Critic&apos;s pushback</p>

      {critique.overOptimisticClaims.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Over-optimistic claims</p>
          <ul className={styles.list}>
            {critique.overOptimisticClaims.map((claim) => (
              <li key={claim}>{claim}</li>
            ))}
          </ul>
        </div>
      )}

      {critique.omittedSecondOrderEffects.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Omitted second-order effects</p>
          <ul className={styles.list}>
            {critique.omittedSecondOrderEffects.map((effect) => (
              <li key={effect}>{effect}</li>
            ))}
          </ul>
        </div>
      )}

      <p className={styles.confidenceNote}>{critique.revisedConfidenceNote}</p>
    </div>
  );
}
