import styles from "./ConfidenceMeter.module.css";

export interface ConfidenceMeterProps {
  /** 0.0-1.0, mirrors `EvidenceBundle.confidence`. */
  confidence: number;
  className?: string;
}

interface ConfidenceBucket {
  readonly maxExclusive: number;
  readonly label: string;
  readonly toneClass: string;
}

/**
 * Thresholds are a UI presentation choice for legibility, not a mirror of
 * any backend confidence-floor constant (those are per-action-tier and
 * owned by the Confidence Arbiter, spec §19.2) — this component only ever
 * displays a score it is given, never computes or gates one.
 */
function buckets(): readonly ConfidenceBucket[] {
  return [
    { maxExclusive: 0.6, label: "Low confidence", toneClass: styles.low },
    { maxExclusive: 0.85, label: "Moderate confidence", toneClass: styles.moderate },
    { maxExclusive: Infinity, label: "High confidence", toneClass: styles.high },
  ];
}

function bucketFor(confidence: number): ConfidenceBucket {
  const found = buckets().find((bucket) => confidence < bucket.maxExclusive);
  return found ?? buckets()[buckets().length - 1];
}

/**
 * Renders confidence as a visual meter plus a qualitative label — this is
 * a trust-building surface (spec §18, human-in-the-loop policy is entirely
 * about making automation legible), so a bare "0.88" is not sufficient on
 * its own; the bar and the bucket label carry the meaning a raw number
 * doesn't.
 */
export function ConfidenceMeter({ confidence, className }: ConfidenceMeterProps) {
  const clamped = Math.min(1, Math.max(0, confidence));
  const percent = Math.round(clamped * 100);
  const bucket = bucketFor(clamped);

  return (
    <div className={[styles.wrapper, className].filter(Boolean).join(" ")}>
      <div
        className={styles.track}
        role="progressbar"
        aria-valuenow={percent}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Confidence"
      >
        <div className={[styles.fill, bucket.toneClass].join(" ")} style={{ width: `${percent}%` }} />
      </div>
      <p className={styles.readout}>
        <span className={styles.percent}>{percent}%</span>
        <span className={[styles.label, bucket.toneClass].join(" ")}>{bucket.label}</span>
      </p>
    </div>
  );
}
