import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { ConfidenceMeter } from "@/components/approvals/ConfidenceMeter";
import { BLOCKER_TYPE_META, type BlockerDiagnosis } from "@/lib/intention-action";
import { BLOCKER_TYPE_ICON, BLOCKER_TYPE_VARIANT } from "./blocker-type-visuals";
import styles from "./DiagnosisDisplay.module.css";

export interface DiagnosisDisplayProps {
  readonly diagnosis: BlockerDiagnosis;
  readonly obligationTitle: string;
  readonly personName: string;
}

/**
 * Renders one real `BlockerDiagnosis` — the obligation, the diagnosed
 * `BlockerType`, and `diagnosisText` shown as a **first-class, standalone
 * statement**, never buried under the confidence number (this phase's
 * brief item 1, and `types.BlockerDiagnosis.diagnosis_text`'s own
 * contract: "a human reading only `diagnosisText` must be able to correct
 * it without decoding a confidence score"). `evidence`, `confidence`, and
 * — when `isRediagnosis` is true — a visible re-diagnosis banner ("the
 * first diagnosis may have been wrong," spec §9.3 Stage 4's own framing)
 * are secondary, supporting detail below it.
 */
export function DiagnosisDisplay({ diagnosis, obligationTitle, personName }: DiagnosisDisplayProps) {
  const Icon = BLOCKER_TYPE_ICON[diagnosis.blockerType];
  const meta = BLOCKER_TYPE_META[diagnosis.blockerType];

  return (
    <Card className={styles.card} title={obligationTitle}>
      <div className={styles.body}>
        <div className={styles.typeRow}>
          <span className={styles.iconWrap} data-variant={BLOCKER_TYPE_VARIANT[diagnosis.blockerType]} aria-hidden="true">
            <Icon size={20} strokeWidth={2} />
          </span>
          <Badge variant={BLOCKER_TYPE_VARIANT[diagnosis.blockerType]}>{meta.label}</Badge>
          <span className={styles.personTag}>for {personName}</span>
        </div>

        {diagnosis.isRediagnosis && (
          <div className={styles.rediagnosisBanner} role="status">
            <strong>This is a re-diagnosis.</strong> The first diagnosis
            {diagnosis.supersededDiagnosisType && (
              <>
                {" "}
                (<em>{BLOCKER_TYPE_META[diagnosis.supersededDiagnosisType].label}</em>)
              </>
            )}{" "}
            may have been wrong — this replaces it, it does not add to it.
          </div>
        )}

        <p className={styles.diagnosisText} data-testid="diagnosis-text">
          &ldquo;{diagnosis.diagnosisText}&rdquo;
        </p>

        <section aria-label="Evidence">
          <h4 className={styles.sectionLabel}>Evidence</h4>
          {diagnosis.evidence.length > 0 ? (
            <ul className={styles.evidenceList}>
              {diagnosis.evidence.map((item, index) => (
                <li key={index}>{item}</li>
              ))}
            </ul>
          ) : (
            <p className={styles.emptyNote}>No supporting evidence recorded for this diagnosis.</p>
          )}
        </section>

        {diagnosis.consideredAlternativeTypes.length > 0 && (
          <section aria-label="Alternatives considered and rejected">
            <h4 className={styles.sectionLabel}>Considered and rejected</h4>
            <div className={styles.alternativesRow}>
              {diagnosis.consideredAlternativeTypes.map((type) => (
                <Badge key={type} variant="neutral">
                  {BLOCKER_TYPE_META[type].label}
                </Badge>
              ))}
            </div>
          </section>
        )}

        <section aria-label="Confidence">
          <h4 className={styles.sectionLabel}>Confidence</h4>
          <ConfidenceMeter confidence={diagnosis.confidence} />
        </section>

        <p className={styles.provenanceLine}>
          {diagnosis.modelTier === "pro" ? "Pro-tier model call" : diagnosis.modelTier} · {diagnosis.promptVersion} ·{" "}
          diagnosed {new Date(diagnosis.diagnosedAt).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" })}
        </p>
      </div>
    </Card>
  );
}
