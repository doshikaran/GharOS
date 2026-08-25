import type { EvidenceBundle } from "@/lib/approvals";
import { ConfidenceMeter } from "./ConfidenceMeter";
import styles from "./EvidenceBundleView.module.css";

export interface EvidenceBundleViewProps {
  bundle: EvidenceBundle;
  className?: string;
}

/**
 * Renders the five things spec §18.2 says "every approval request carries,
 * no exceptions": reasoning, the full evidence-consulted list (never
 * truncated or hidden behind a click), confidence, and consequence-if-wrong.
 * `proposedAction` itself is rendered by the caller as the card's heading,
 * since it is also the thing a screen-reader user hits first.
 *
 * Shared by `ApprovalCard` (the approve/reject queue) and `EscalationCard`
 * (the escalation surface) so both surfaces render the evidence bundle
 * identically — the only thing that should differ between them is which
 * actions are offered underneath it, never how much evidence is shown.
 */
export function EvidenceBundleView({ bundle, className }: EvidenceBundleViewProps) {
  return (
    <div className={[styles.wrapper, className].filter(Boolean).join(" ")}>
      <section aria-label="Reasoning">
        <h4 className={styles.sectionLabel}>Reasoning</h4>
        <p className={styles.reasoning}>{bundle.reasoning}</p>
      </section>

      <section aria-label="Evidence consulted">
        <h4 className={styles.sectionLabel}>Evidence consulted ({bundle.evidenceConsulted.length})</h4>
        <ul className={styles.evidenceList}>
          {bundle.evidenceConsulted.map((entry) => (
            <li key={entry} className={styles.evidenceItem}>
              {entry}
            </li>
          ))}
        </ul>
      </section>

      <section aria-label="Confidence">
        <h4 className={styles.sectionLabel}>Confidence</h4>
        <ConfidenceMeter confidence={bundle.confidence} />
      </section>

      <section aria-label="Consequence if wrong" className={styles.consequenceSection}>
        <h4 className={styles.sectionLabel}>If this is wrong</h4>
        <p className={styles.consequence}>{bundle.consequenceIfWrong}</p>
      </section>
    </div>
  );
}
