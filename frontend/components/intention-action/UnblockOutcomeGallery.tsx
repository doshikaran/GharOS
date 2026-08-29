import { ArrowRight, type LucideIcon } from "lucide-react";
import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import {
  AVERSION_MODALITY_LABEL,
  type DecisionNarrowingResult,
  type InformationFetchResult,
  type ModalitySwitchResult,
  type WindowFindingResult,
} from "@/lib/intention-action";
import { BLOCKER_TYPE_ICON, BLOCKER_TYPE_VARIANT } from "./blocker-type-visuals";
import styles from "./UnblockOutcomeGallery.module.css";

export interface UnblockOutcomeGalleryProps {
  readonly informationOutcome: InformationFetchResult;
  readonly decisionOutcome: DecisionNarrowingResult;
  readonly aversionOutcome: ModalitySwitchResult;
  readonly windowOutcome: WindowFindingResult;
  readonly windowPersonName: string;
}

function formatWindow(window: readonly [string, string]): string {
  const start = new Date(window[0]);
  const end = new Date(window[1]);
  const dateLabel = start.toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });
  const startLabel = start.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "UTC" });
  const endLabel = end.toLocaleTimeString("en-IN", { hour: "numeric", minute: "2-digit", timeZone: "UTC" });
  return `${dateLabel}, ${startLabel}–${endLabel}`;
}

const VERDICT_LABEL: Record<string, string> = {
  available: "Available",
  hard_blocked: "Hard blocked",
  soft_avoid: "Soft, avoid if possible",
  cannot_determine: "Cannot determine",
  unavailable: "Unavailable",
  likely: "Likely",
  unlikely: "Unlikely",
  insufficient_data: "Insufficient data",
};

/**
 * The four Gate-9-named unblock outcomes, each shown as a real before/after
 * — what actually happened, not a description of what A24/A25 generically
 * do (this phase's brief item 3).
 */
export function UnblockOutcomeGallery({
  informationOutcome,
  decisionOutcome,
  aversionOutcome,
  windowOutcome,
  windowPersonName,
}: UnblockOutcomeGalleryProps) {
  const InfoIcon = BLOCKER_TYPE_ICON.information;
  const DecisionIcon = BLOCKER_TYPE_ICON.decision;
  const AversionIcon = BLOCKER_TYPE_ICON.aversion;
  const WindowIcon = BLOCKER_TYPE_ICON.window;

  return (
    <div className={styles.grid}>
      <Card className={styles.outcomeCard} title={<OutcomeTitle icon={InfoIcon} variant={BLOCKER_TYPE_VARIANT.information} label="Information blocker → fact fetched" />}>
        {informationOutcome.fetched ? (
          <>
            <p className={styles.beforeAfterLabel}>Before</p>
            <p className={styles.before}>{informationOutcome.missingFactDescription}, unknown.</p>
            <p className={styles.beforeAfterLabel}>After</p>
            <p className={styles.after}>{informationOutcome.factText}</p>
          </>
        ) : (
          <p className={styles.notFetched}>
            The graph had no answer for &ldquo;{informationOutcome.missingFactDescription}&rdquo;, nothing was
            fabricated; this stays open for a human.
          </p>
        )}
        <ConfidenceLine confidence={informationOutcome.confidence} modelTier={informationOutcome.modelTier} />
      </Card>

      <Card className={styles.outcomeCard} title={<OutcomeTitle icon={DecisionIcon} variant={BLOCKER_TYPE_VARIANT.decision} label="Decision blocker → narrowed to binary" />}>
        <p className={styles.beforeAfterLabel}>Before</p>
        <p className={styles.before}>An open decision with no stated options.</p>
        <p className={styles.beforeAfterLabel}>After, two real, mutually exclusive options</p>
        <div className={styles.optionPair}>
          <span className={styles.option} data-testid="decision-option-a">
            {decisionOutcome.optionA}
          </span>
          <span className={styles.optionDivider}>or</span>
          <span className={styles.option} data-testid="decision-option-b">
            {decisionOutcome.optionB}
          </span>
        </div>
        <p className={styles.reasoning}>{decisionOutcome.framingText}</p>
        <ConfidenceLine confidence={decisionOutcome.confidence} modelTier={decisionOutcome.modelTier} />
      </Card>

      <Card className={styles.outcomeCard} title={<OutcomeTitle icon={AversionIcon} variant={BLOCKER_TYPE_VARIANT.aversion} label="Aversion blocker → modality switched" />}>
        <div className={styles.modalitySwitchRow}>
          <Badge variant="neutral">{AVERSION_MODALITY_LABEL[aversionOutcome.fromModality]}</Badge>
          <ArrowRight size={16} aria-hidden="true" />
          <Badge variant="danger">{AVERSION_MODALITY_LABEL[aversionOutcome.toModality]}</Badge>
        </div>
        <p className={styles.beforeAfterLabel}>Pre-drafted, ready to send</p>
        <p className={styles.after}>&ldquo;{aversionOutcome.preDraftedText}&rdquo;</p>
        <p className={styles.reasoning}>{aversionOutcome.reasoning}</p>
        <ConfidenceLine confidence={aversionOutcome.confidence} modelTier={aversionOutcome.modelTier} />
      </Card>

      <Card className={styles.outcomeCard} title={<OutcomeTitle icon={WindowIcon} variant={BLOCKER_TYPE_VARIANT.window} label="Window blocker → AvailabilityVerdict" />}>
        <ul className={styles.evaluationList}>
          {windowOutcome.evaluations.map((evaluation) => (
            <li key={evaluation.window[0]} className={styles.evaluationRow} data-recommended={evaluation.overallRecommended}>
              <span className={styles.evaluationWindow}>{formatWindow(evaluation.window)}</span>
              <span className={styles.verdictBadges}>
                <Badge variant={evaluation.personAvailability === "available" ? "success" : evaluation.personAvailability === "hard_blocked" ? "danger" : evaluation.personAvailability === "soft_avoid" ? "warning" : "neutral"}>
                  {windowPersonName}: {VERDICT_LABEL[evaluation.personAvailability]}
                </Badge>
                {evaluation.counterpartyAvailability && (
                  <Badge variant="info">Provider: {VERDICT_LABEL[evaluation.counterpartyAvailability]}</Badge>
                )}
                <Badge variant="neutral">History: {VERDICT_LABEL[evaluation.historicalLikelihood]}</Badge>
              </span>
              {evaluation.overallRecommended && <Badge variant="brass">Recommended</Badge>}
            </li>
          ))}
        </ul>
        <ConfidenceLine confidence={windowOutcome.confidence} modelTier={windowOutcome.modelTier} />
      </Card>
    </div>
  );
}

function OutcomeTitle({ icon: Icon, variant, label }: { icon: LucideIcon; variant: string; label: string }) {
  return (
    <span className={styles.titleRow}>
      <span className={styles.titleIconWrap} data-variant={variant} aria-hidden="true">
        <Icon size={18} strokeWidth={2} />
      </span>
      {label}
    </span>
  );
}

function ConfidenceLine({ confidence, modelTier }: { confidence: number; modelTier: string }) {
  return (
    <p className={styles.confidenceLine}>
      {Math.round(confidence * 100)}% confidence · {modelTier === "deterministic" ? "deterministic, no model call" : `${modelTier}-tier model call`}
    </p>
  );
}
