import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { ConfidenceMeter } from "@/components/approvals/ConfidenceMeter";
import {
  BLOCKER_TYPE_META,
  type EscalationOption,
  type SlippageAnalysisResult,
  type UnblockingAttempt,
} from "@/lib/intention-action";
import { BLOCKER_TYPE_ICON, BLOCKER_TYPE_VARIANT } from "./blocker-type-visuals";
import styles from "./SlippageEscalationSurface.module.css";

export interface SlippageEscalationSurfaceProps {
  readonly obligationTitle: string;
  readonly attempts: readonly UnblockingAttempt[];
  readonly analysis: SlippageAnalysisResult;
  readonly delegateName: (personId: string) => string;
}

const OPTION_LABEL: Record<EscalationOption["kind"], string> = {
  drop: "Drop it",
  delegate: "Delegate it",
  pay: "Pay someone",
};

function formatCurrency(amount: number): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", minimumFractionDigits: 0 }).format(amount);
}

/**
 * A real rendering of A26's escalation — repeat-failure history, the
 * re-diagnosis framing, and the three real drop/delegate/pay options, each
 * with enough context a human could actually decide (this phase's brief
 * item 4, matching `DisputeSurface`'s "give a human what they need to
 * decide, never auto-resolve" discipline exactly: there is no "choose
 * this option" button anywhere in this component — presenting the options
 * is the whole job).
 */
export function SlippageEscalationSurface({ obligationTitle, attempts, analysis, delegateName }: SlippageEscalationSurfaceProps) {
  return (
    <div className={styles.wrapper}>
      <Card className={styles.card} title={`Repeat-failure history — ${obligationTitle}`}>
        <ol className={styles.attemptList}>
          {attempts.map((attempt) => {
            const meta = BLOCKER_TYPE_META[attempt.diagnosis.blockerType];
            const Icon = BLOCKER_TYPE_ICON[attempt.diagnosis.blockerType];
            return (
              <li key={attempt.attemptNumber} className={styles.attemptRow}>
                <div className={styles.attemptHeader}>
                  <span className={styles.attemptNumber}>Attempt {attempt.attemptNumber}</span>
                  <span className={styles.iconWrap} data-variant={BLOCKER_TYPE_VARIANT[attempt.diagnosis.blockerType]} aria-hidden="true">
                    <Icon size={14} strokeWidth={2} />
                  </span>
                  <Badge variant={BLOCKER_TYPE_VARIANT[attempt.diagnosis.blockerType]}>{meta.label}</Badge>
                  <Badge variant={attempt.outcome === "failed" ? "danger" : "success"}>
                    {attempt.outcome === "failed" ? "Failed" : "Succeeded"}
                  </Badge>
                  <span className={styles.attemptDate}>
                    {new Date(attempt.attemptedAt).toLocaleDateString("en-IN", { dateStyle: "medium", timeZone: "UTC" })}
                  </span>
                </div>
                <p className={styles.attemptAction}>{attempt.actionTaken}</p>
              </li>
            );
          })}
        </ol>
      </Card>

      {analysis.escalationTriggered && (
        <Card className={styles.card} title="Escalation">
          <p className={styles.escalationMessage} role="status">
            {analysis.messageText}
          </p>

          {analysis.reDiagnosis && (
            <div className={styles.reDiagnosisBanner}>
              <strong>Re-diagnosis:</strong> likely a{" "}
              <Badge variant={BLOCKER_TYPE_VARIANT[analysis.reDiagnosis.likelyBlockerType]}>
                {BLOCKER_TYPE_META[analysis.reDiagnosis.likelyBlockerType].label}
              </Badge>
              {analysis.reDiagnosis.changedFromPrior && " — the first diagnosis may have been wrong."}
              <p className={styles.reDiagnosisReasoning}>{analysis.reDiagnosis.reasoning}</p>
              <ConfidenceMeter confidence={analysis.reDiagnosis.confidence} />
            </div>
          )}

          <h4 className={styles.optionsHeading}>Real options — a human decides, never auto-resolved</h4>
          <div className={styles.optionsGrid}>
            {analysis.escalationOptions.map((option) => (
              <div key={option.kind} className={styles.optionCard} data-testid={`escalation-option-${option.kind}`}>
                <Badge variant={option.kind === "drop" ? "neutral" : option.kind === "delegate" ? "info" : "brass"}>
                  {OPTION_LABEL[option.kind]}
                </Badge>
                <p className={styles.optionDescription}>{option.description}</p>
                {option.kind === "delegate" && option.candidatePersonId && (
                  <p className={styles.optionDetail}>Candidate: {delegateName(option.candidatePersonId)}</p>
                )}
                {option.kind === "pay" && option.estimatedCost !== null && (
                  <p className={styles.optionDetail}>Estimated cost: {formatCurrency(option.estimatedCost)}</p>
                )}
              </div>
            ))}
          </div>
        </Card>
      )}
    </div>
  );
}
