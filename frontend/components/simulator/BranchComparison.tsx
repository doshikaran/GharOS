import type { BranchCritique, BranchProjection, GroundingResult } from "@/lib/simulator";
import { BranchCard } from "./BranchCard";
import styles from "./BranchComparison.module.css";

export interface BranchComparisonProps {
  readonly projections: readonly BranchProjection[];
  readonly groundingResults: readonly GroundingResult[];
  readonly critiques: readonly BranchCritique[];
}

/**
 * 2-4 branches side by side (this phase's brief). Joins three
 * independently-produced agent outputs — A37's projections, A36's
 * grounding, A38's critiques — by `label`/`branchId` at render time,
 * rather than assuming a positional match.
 */
export function BranchComparison({ projections, groundingResults, critiques }: BranchComparisonProps) {
  const groundingByLabel = new Map(groundingResults.map((result) => [result.branchLabel, result]));
  const critiqueByBranchId = new Map(critiques.map((critique) => [critique.branchId, critique]));

  return (
    <div className={styles.grid} role="list" aria-label="Branch comparison">
      {projections.map((projection) => (
        <div key={projection.branchId} role="listitem">
          <BranchCard
            projection={projection}
            grounding={groundingByLabel.get(projection.label)}
            critique={critiqueByBranchId.get(projection.branchId)}
          />
        </div>
      ))}
    </div>
  );
}
