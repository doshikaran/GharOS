import { agentShortLabel, branchLabel, eliminatingAgentForBranch, type SpecialistPosition } from "@/lib/council";
import styles from "./EliminatedBranches.module.css";

export interface EliminatedBranchesProps {
  readonly eliminatedBranchIds: readonly string[];
  readonly positions: readonly SpecialistPosition[];
}

/**
 * Hard-constraint elimination, rendered as elimination — never a low
 * score (Gate 12: "Care's hard constraint ELIMINATES options, does not
 * score them down"). Every eliminated branch appears here, struck
 * through, in its own section, named alongside the specialist who
 * eliminated it and that specialist's own reasoning — never mixed back
 * into a list of surviving options where it could be mistaken for one
 * that "just scored badly."
 */
export function EliminatedBranches({ eliminatedBranchIds, positions }: EliminatedBranchesProps) {
  if (eliminatedBranchIds.length === 0) {
    return <p className={styles.empty}>No hard constraint eliminated any option this round.</p>;
  }

  return (
    <ul className={styles.list} aria-label="Eliminated options">
      {eliminatedBranchIds.map((branchId) => {
        const eliminatingAgentId = eliminatingAgentForBranch(positions, branchId);
        const eliminatingPosition = positions.find((position) => position.agentId === eliminatingAgentId);
        return (
          <li key={branchId} className={styles.row}>
            <p className={styles.branchLabel}>
              <s>{branchLabel(branchId)}</s>
            </p>
            <p className={styles.eliminatedBy}>
              Eliminated by {eliminatingAgentId ? agentShortLabel(eliminatingAgentId) : "an unrecorded specialist"} —
              a hard constraint, not a low score.
            </p>
            {eliminatingPosition && <p className={styles.reason}>{eliminatingPosition.reasoning}</p>}
          </li>
        );
      })}
    </ul>
  );
}
