import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { ConfidenceMeter } from "@/components/approvals/ConfidenceMeter";
import { MAX_CLARIFYING_QUESTIONS, type ClarificationResult } from "@/lib/concierge";
import styles from "./ClarificationDisplay.module.css";

export interface ClarificationDisplayProps {
  readonly result: ClarificationResult;
  readonly personName: string;
}

/**
 * Renders A50's real `ClarificationResult` (this phase's brief item 1):
 * what the graph already answered, shown plainly and first — so a reader
 * sees immediately that these were never asked about — and the real
 * questions A50 actually decided to ask, never more than
 * `MAX_CLARIFYING_QUESTIONS` (Gate 10's own literal ceiling). When a
 * scenario has more genuine candidate unknowns than the ceiling allows,
 * the surplus surfaces as `assumptions` instead of being silently
 * dropped — rendered here too, so the ceiling reads as a real, enforced
 * cutoff rather than a lucky coincidence of this one fixture.
 */
export function ClarificationDisplay({ result, personName }: ClarificationDisplayProps) {
  const atCeiling = result.questions.length >= MAX_CLARIFYING_QUESTIONS;

  return (
    <div className={styles.wrapper}>
      <Card className={styles.card} title="Already known from the household graph — never asked about">
        <ul className={styles.factList}>
          {result.resolvedFromGraph.map((fact) => (
            <li key={fact.field} className={styles.factRow}>
              <span className={styles.factField}>{humanizeField(fact.field)}</span>
              <span className={styles.factValue}>{fact.value}</span>
              <span className={styles.factSource}>{fact.source}</span>
            </li>
          ))}
        </ul>
      </Card>

      <Card
        className={styles.card}
        title={
          <span className={styles.questionsTitleRow}>
            <span>
              What genuinely can&apos;t be answered from the graph — {result.questions.length} question
              {result.questions.length === 1 ? "" : "s"} asked
            </span>
            <Badge variant={atCeiling ? "brass" : "neutral"}>
              {result.questions.length} / {MAX_CLARIFYING_QUESTIONS} max
            </Badge>
          </span>
        }
      >
        <ol className={styles.questionList}>
          {result.questions.map((question) => (
            <li key={question.targetsUnknown} className={styles.questionRow}>
              <p className={styles.questionText}>{question.text}</p>
              <p className={styles.questionRelevance}>{question.decisionRelevance}</p>
            </li>
          ))}
        </ol>

        {result.assumptions.length > 0 && (
          <div className={styles.assumptionsBlock}>
            <h4 className={styles.assumptionsHeading}>
              Genuinely unknown too, but past the {MAX_CLARIFYING_QUESTIONS}-question ceiling — assumed instead
              of asked
            </h4>
            <ul className={styles.assumptionsList}>
              {result.assumptions.map((assumption) => (
                <li key={assumption}>{assumption}</li>
              ))}
            </ul>
          </div>
        )}
      </Card>

      <Card className={styles.card} title="Urgency">
        <div className={styles.urgencyRow}>
          <Badge variant={result.urgency === "elevated" ? "danger" : "neutral"}>
            {result.urgency === "elevated" ? "Elevated" : "Routine"}
          </Badge>
          <p className={styles.urgencyReasoning}>{result.urgencyReasoning}</p>
        </div>
        <div className={styles.confidenceRow}>
          <span className={styles.confidenceLabel}>Clarification confidence</span>
          <ConfidenceMeter confidence={result.confidence} />
        </div>
      </Card>

      <p className={styles.requestLine}>
        <strong>{personName}&apos;s household request:</strong> &ldquo;{result.householdRequestText}&rdquo;
      </p>
    </div>
  );
}

const FIELD_LABEL: Readonly<Record<string, string>> = {
  last_visit_date: "Last visit",
  insurance_coverage: "Insurance",
  availability_model: "Availability",
  prior_provider_history: "Prior provider history",
};

function humanizeField(field: string): string {
  return FIELD_LABEL[field] ?? field.replace(/_/g, " ");
}
