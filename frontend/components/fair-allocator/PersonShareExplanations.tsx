import { Card } from "@/components/design-system/Card";
import { ConfidenceMeter } from "@/components/approvals/ConfidenceMeter";
import type { PersonShareExplanation } from "@/lib/fair-allocator";
import styles from "./PersonShareExplanations.module.css";

export interface PersonShareExplanationsProps {
  readonly explanations: readonly PersonShareExplanation[];
  readonly personName: (personId: string) => string;
  readonly taskTitle: (taskId: string) => string;
}

/**
 * Renders every real `PersonShareExplanation` (A19) — one card per person,
 * each one visibly grounded in *that specific person's own* tasks and
 * costs (spec §15.8 A19: "explain each share in that person's own
 * valuations"), never a generic templated sentence interchangeable
 * between people (PHASES.md Phase 8, E4 work item 2).
 */
export function PersonShareExplanations({ explanations, personName, taskTitle }: PersonShareExplanationsProps) {
  if (explanations.length === 0) {
    return <p className={styles.emptyState}>No per-person explanations for this cycle yet.</p>;
  }

  return (
    <div className={styles.grid}>
      {explanations.map((explanation) => (
        <Card key={explanation.personId} title={personName(explanation.personId)} className={styles.card}>
          <ul className={styles.taskList}>
            {explanation.taskIds.map((taskId) => (
              <li key={taskId}>{taskTitle(taskId)}</li>
            ))}
          </ul>
          <p className={styles.total}>
            Total cost to {personName(explanation.personId)}: <strong>{explanation.totalCostToSelf.toFixed(1)}</strong>
          </p>
          <p className={styles.explanationText}>{explanation.explanationText}</p>
          <div className={styles.confidenceRow}>
            <span className={styles.confidenceLabel}>Explanation confidence</span>
            <ConfidenceMeter confidence={explanation.confidence} />
          </div>
        </Card>
      ))}
    </div>
  );
}
