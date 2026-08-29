import { Badge } from "@/components/design-system/Badge";
import type { CouncilStance } from "@/lib/council";
import type { DecisionReplay } from "@/lib/council-history";
import styles from "./DecisionReplayPanel.module.css";

export interface DecisionReplayPanelProps {
  readonly replay: DecisionReplay;
}

const STANCE_BADGE_VARIANT: Record<CouncilStance, "success" | "danger" | "neutral"> = {
  supports: "success",
  opposes: "danger",
  neutral: "neutral",
};

/**
 * "Why did we buy this car?" (spec §12.4's own closing promise, PHASES.md
 * Phase 12) — the full replay of one past `Decision`: its trigger, every
 * `Branch` it considered, every `CouncilPosition` naming it (never
 * summarised — each position keeps its own agent, stance, reasoning, and
 * evidence), and who is recorded as having conceded via a real
 * `CONCEDED_BY` edge. This is the permanent record persisting exactly
 * what `CouncilExplorer` shows live, read back two years later.
 */
export function DecisionReplayPanel({ replay }: DecisionReplayPanelProps) {
  const { decision, branches, positions, conceders } = replay;
  const branchById = new Map(branches.map((branch) => [branch.id, branch] as const));

  return (
    <div className={styles.panel}>
      <header className={styles.header}>
        <h3 className={styles.question}>{decision.question}</h3>
        <Badge variant={decision.status === "resolved" ? "success" : "neutral"}>{decision.status || "unknown"}</Badge>
      </header>

      {decision.trigger && (
        <p className={styles.trigger}>
          <strong>Trigger — </strong>
          {decision.trigger}
        </p>
      )}

      {decision.resolutionSummary && (
        <p className={styles.resolutionSummary}>
          <strong>Resolution — </strong>
          {decision.resolutionSummary}
        </p>
      )}

      {decision.rationale && (
        <p className={styles.rationale}>
          <strong>Rationale — </strong>
          {decision.rationale}
        </p>
      )}

      <section aria-label="Branches considered">
        <h4 className={styles.subheading}>Branches considered</h4>
        {branches.length === 0 ? (
          <p className={styles.empty}>No branches recorded for this decision.</p>
        ) : (
          <ul className={styles.branchList}>
            {branches.map((branch) => (
              <li key={branch.id} className={styles.branchCard}>
                <p className={styles.branchLabel}>{branch.label}</p>
                {Object.entries(branch.projectedImpacts).length > 0 && (
                  <ul className={styles.impactList}>
                    {Object.entries(branch.projectedImpacts).map(([dimension, impact]) => (
                      <li key={dimension} className={styles.impactRow}>
                        <span className={styles.impactDimension}>{dimension}</span>: {impact}
                      </li>
                    ))}
                  </ul>
                )}
                {branch.critiques.length > 0 && (
                  <ul className={styles.critiqueList} aria-label={`Critiques of ${branch.label}`}>
                    {branch.critiques.map((critique, index) => (
                      <li key={index} className={styles.critiqueRow}>
                        {critique}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Council positions">
        <h4 className={styles.subheading}>Every council position naming this decision</h4>
        {positions.length === 0 ? (
          <p className={styles.empty}>No council positions recorded for this decision.</p>
        ) : (
          <ul className={styles.positionList}>
            {positions.map((position) => (
              <li key={position.id} className={styles.positionCard}>
                <div className={styles.positionHeader}>
                  <span className={styles.agentName}>{position.heldByAgent}</span>
                  <Badge variant={STANCE_BADGE_VARIANT[position.stance]}>{position.stance}</Badge>
                </div>
                {position.branchId && (
                  <p className={styles.positionBranch}>
                    On: {branchById.get(position.branchId)?.label ?? position.branchId}
                  </p>
                )}
                <p className={styles.positionReasoning}>{position.reasoning}</p>
                {position.evidenceRefs.length > 0 && (
                  <ul className={styles.evidenceList}>
                    {position.evidenceRefs.map((ref) => (
                      <li key={ref} className={styles.evidenceChip}>
                        {ref}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Who conceded">
        <h4 className={styles.subheading}>Who conceded</h4>
        {conceders.length === 0 ? (
          <p className={styles.empty}>No concession recorded on this decision.</p>
        ) : (
          <ul className={styles.concederList}>
            {conceders.map((conceder) => (
              <li key={conceder.personId} className={styles.concederChip}>
                {conceder.personLabel}
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
