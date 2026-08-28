import type { BranchCritique, BranchProjection, GroundingResult } from "@/lib/simulator";
import { BranchCritiqueView } from "./BranchCritiqueView";
import { BranchGroundingCitations } from "./BranchGroundingCitations";
import styles from "./BranchCard.module.css";

export interface BranchCardProps {
  readonly projection: BranchProjection;
  readonly grounding: GroundingResult | undefined;
  readonly critique: BranchCritique | undefined;
}

/**
 * One branch of the comparison (this phase's brief: "each showing its
 * projected impacts, its grounding citations..., and its critique...
 * called out distinctly, not blended into the projection"). Three
 * visually separate sections in a fixed order — projection, then
 * grounding, then critique — so a viewer reads the critic's pushback as a
 * response to what came before it, never as part of the same claim.
 */
export function BranchCard({ projection, grounding, critique }: BranchCardProps) {
  return (
    <article className={styles.card} aria-label={`Branch: ${projection.label}`}>
      <h3 className={styles.label}>{projection.label}</h3>

      <section aria-label="Projected impacts">
        <p className={styles.sectionLabel}>Projected impacts</p>
        <dl className={styles.impactList}>
          {Object.entries(projection.projectedImpacts).map(([category, text]) => (
            <div key={category} className={styles.impactRow}>
              <dt className={styles.impactCategory}>{category}</dt>
              <dd className={styles.impactText}>{text}</dd>
            </div>
          ))}
        </dl>
      </section>

      {projection.blastRadiusNodeIds.length > 0 && (
        <section aria-label="Blast radius" className={styles.blastRadius}>
          <p className={styles.sectionLabel}>Blast radius ({projection.blastRadiusNodeIds.length} nodes)</p>
          <div className={styles.nodeChips}>
            {projection.blastRadiusNodeIds.map((nodeId) => (
              <span key={nodeId} className={styles.nodeChip}>
                {nodeId}
              </span>
            ))}
          </div>
        </section>
      )}

      <section aria-label="Grounding">
        <p className={styles.sectionLabel}>Grounding</p>
        <BranchGroundingCitations grounding={grounding} />
      </section>

      <BranchCritiqueView critique={critique} />
    </article>
  );
}
