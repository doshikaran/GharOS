import { Badge } from "@/components/design-system/Badge";
import { MIN_SAMPLE_SIZE_FOR_CALIBRATION, type CalibrationEstimate } from "@/lib/simulator";
import styles from "./CalibrationPanel.module.css";

export interface CalibrationPanelProps {
  readonly estimate: CalibrationEstimate | undefined;
}

/**
 * A39 Calibration's output: this household's own variance for the
 * decision's category, or — below `MIN_SAMPLE_SIZE_FOR_CALIBRATION` — the
 * honest thin-history statement instead of a manufactured number (spec
 * §11.5, ADR-017 Decision 1: "thin history... says so, never fabricates
 * precision"). The thin-history case is rendered as its own distinct,
 * clearly-labelled callout — a named failure mode, never a blank or
 * loading-looking gap (this phase's brief).
 */
export function CalibrationPanel({ estimate }: CalibrationPanelProps) {
  if (!estimate) {
    return (
      <p className={styles.unavailable} role="status">
        No calibration history on file for this decision&apos;s category yet.
      </p>
    );
  }

  return (
    <div className={styles.panel} aria-label="Calibration">
      <div className={styles.headingRow}>
        <p className={styles.categoryTag}>category: {estimate.categoryTag}</p>
        {estimate.isThinHistory ? (
          <Badge variant="warning">Thin history</Badge>
        ) : (
          <Badge variant="success">Calibrated</Badge>
        )}
      </div>

      {estimate.isThinHistory ? (
        <div className={styles.thinHistoryCallout}>
          <p className={styles.thinHistoryHeading}>
            Only {estimate.sampleSize} prior outcome{estimate.sampleSize === 1 ? "" : "s"} on file, below the
            minimum of {MIN_SAMPLE_SIZE_FOR_CALIBRATION} needed for a variance estimate
          </p>
          <p className={styles.honestNote}>{estimate.honestNote}</p>
        </div>
      ) : (
        <>
          <div className={styles.statsRow}>
            <div className={styles.stat}>
              <span className={styles.statLabel}>Sample size</span>
              <span className={styles.statValue}>{estimate.sampleSize}</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statLabel}>Mean variance</span>
              <span className={styles.statValue}>{estimate.meanVariance}</span>
            </div>
            <div className={styles.stat}>
              <span className={styles.statLabel}>Std. deviation</span>
              <span className={styles.statValue}>{estimate.stdevVariance}</span>
            </div>
          </div>
          {estimate.confidenceBandNote && <p className={styles.confidenceBand}>{estimate.confidenceBandNote}</p>}
          <p className={styles.honestNote}>{estimate.honestNote}</p>
        </>
      )}
    </div>
  );
}
