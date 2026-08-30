import type { BackwardModeAnalysis } from "@/lib/simulator";
import styles from "./BackwardModeView.module.css";

export interface BackwardModeViewProps {
  readonly analysis: BackwardModeAnalysis;
}

/**
 * Backward mode (ADR-017 Decision 3): the same six agents' second entry
 * point — "take a committed plan → assume it failed → reason backwards
 * using OUTCOME history → identify the likely failure point → hand
 * mitigations to Intention→Action." Rendered as a distinct, clearly-
 * labelled secondary view (this phase's brief), captioned explicitly as
 * informational — never an automatic action. Nothing rendered here writes
 * to Intention→Action; the mitigations are suggestions for a human to
 * act on by hand.
 */
export function BackwardModeView({ analysis }: BackwardModeViewProps) {
  return (
    <div className={styles.view} aria-label="Backward mode">
      <p className={styles.informationalNote} role="note">
        Informational only. GharOS does not automatically act on anything below, no task is created or changed
        in Intention → Action from this view.
      </p>

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Committed plan</p>
        <p className={styles.text}>{analysis.planDescription}</p>
      </div>

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Assumed failure point</p>
        <p className={`${styles.text} ${styles.failurePoint}`}>{analysis.assumedFailurePoint}</p>
      </div>

      {analysis.supportingOutcomeIds.length > 0 && (
        <div className={styles.section}>
          <p className={styles.sectionLabel}>Supporting outcomes ({analysis.supportingOutcomeIds.length})</p>
          <div className={styles.outcomeChips}>
            {analysis.supportingOutcomeIds.map((id) => (
              <span key={id} className={styles.outcomeChip}>
                {id}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Confidence</p>
        <p className={styles.text}>{analysis.confidenceNote}</p>
      </div>

      <div className={styles.section}>
        <p className={styles.sectionLabel}>Suggested mitigations</p>
        <ul className={styles.list}>
          {analysis.suggestedMitigations.map((mitigation) => (
            <li key={mitigation}>{mitigation}</li>
          ))}
        </ul>
      </div>
    </div>
  );
}
