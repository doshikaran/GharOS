import styles from "./DerivationBadge.module.css";

/**
 * Mirrors `contracts.graph_types.Derivation` exactly — "extracted" |
 * "inferred" | "ambiguous" — so this component can be driven directly by
 * a node/edge's `provenance.derivation` field with no translation layer.
 */
export type DerivationTag = "extracted" | "inferred" | "ambiguous";

export interface DerivationBadgeProps {
  derivation: DerivationTag;
  /** 0.0-1.0, mirrors `Provenance.confidence`. Shown as a percentage when provided. */
  confidence?: number;
  className?: string;
}

const LABEL: Record<DerivationTag, string> = {
  extracted: "Extracted",
  inferred: "Inferred",
  ambiguous: "Ambiguous",
};

const VARIANT_CLASS: Record<DerivationTag, string> = {
  extracted: styles.extracted,
  inferred: styles.inferred,
  ambiguous: styles.ambiguous,
};

/**
 * The load-bearing derivation marker (spec §5.6, §5.8). Renders the same
 * solid / dashed / dotted border convention used to style graph edges by
 * derivation tag, so this badge and the graph visualisation teach the same
 * visual language. Colour reinforces but never substitutes for the border
 * style — the encoding must still read correctly for colour-blind users.
 */
export function DerivationBadge({ derivation, confidence, className }: DerivationBadgeProps) {
  const classes = [styles.badge, VARIANT_CLASS[derivation], className]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} data-derivation={derivation}>
      <span className={styles.dot} aria-hidden="true" />
      {LABEL[derivation]}
      {confidence !== undefined && (
        <span className={styles.confidence}>{Math.round(confidence * 100)}%</span>
      )}
    </span>
  );
}
