import { Badge } from "@/components/design-system/Badge";
import { agentDomainLabel, agentShortLabel, branchLabel, type CouncilStance, type SpecialistPosition } from "@/lib/council";
import styles from "./SpecialistPositions.module.css";

export interface SpecialistPositionsProps {
  readonly positions: readonly SpecialistPosition[];
}

const STANCE_BADGE_VARIANT: Record<CouncilStance, "success" | "danger" | "neutral"> = {
  supports: "success",
  opposes: "danger",
  neutral: "neutral",
};

/**
 * Every specialist's own reported position — Phase 1 "independent
 * reporting" made visible (spec §12.3): each card names the subgraph that
 * specialist queried, so a viewer can see Finance and Care are reporting
 * from genuinely different kinds of evidence (real ledger figures vs a
 * real mobility constraint), never generic interchangeable prose. Never
 * blended into a single synthesized paragraph — one card per specialist,
 * each with its own reasoning and its own evidence.
 */
export function SpecialistPositions({ positions }: SpecialistPositionsProps) {
  return (
    <ul className={styles.list} aria-label="Specialist positions">
      {positions.map((position) => (
        <li key={position.agentId} className={styles.card}>
          <div className={styles.header}>
            <div>
              <p className={styles.agentName}>{agentShortLabel(position.agentId)}</p>
              <p className={styles.agentDomain}>{agentDomainLabel(position.agentId)}</p>
            </div>
            <Badge variant={STANCE_BADGE_VARIANT[position.stance]}>{position.stance}</Badge>
          </div>

          <p className={styles.reasoning}>{position.reasoning}</p>

          {position.eliminatedBranchIds.length > 0 && (
            <p className={styles.eliminationNote} role="note">
              Hard constraint, eliminates{" "}
              {position.eliminatedBranchIds.map((branchId, index) => (
                <span key={branchId}>
                  {index > 0 && ", "}
                  <strong>{branchLabel(branchId)}</strong>
                </span>
              ))}{" "}
              from consideration entirely, not scored down against the surviving options.
            </p>
          )}

          <div className={styles.evidence}>
            <p className={styles.evidenceLabel}>Evidence</p>
            <ul className={styles.evidenceList}>
              {position.evidenceRefs.map((ref) => (
                <li key={ref} className={styles.evidenceChip}>
                  {ref}
                </li>
              ))}
            </ul>
          </div>
        </li>
      ))}
    </ul>
  );
}
