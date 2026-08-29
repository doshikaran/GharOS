import { branchLabel, type AdversaryAttack } from "@/lib/council";
import styles from "./AdversaryAttackView.module.css";

export interface AdversaryAttackViewProps {
  readonly attack: AdversaryAttack;
}

/**
 * A48 Council Adversary's attack on the arbiter's own winning branch
 * (ADR-019 Decision 7 — there is no separate, earlier "leading option";
 * the Adversary attacks the same option the deterministic arbiter picked).
 * Rendered in its own visually distinct section, never folded in among
 * the specialist positions above — it is adversarial by design (spec
 * §12.2: "critiques *another* agent's output — the pattern the literature
 * shows works, unlike self-critique"), not a sixth position reported
 * alongside the other five.
 */
export function AdversaryAttackView({ attack }: AdversaryAttackViewProps) {
  return (
    <section className={styles.panel} aria-label="Adversary attack">
      <p className={styles.kicker}>Structurally tasked with attacking the leading option, not a position</p>
      <p className={styles.target}>Target: {branchLabel(attack.targetBranchId)}</p>
      <p className={styles.critique}>{attack.critique}</p>

      <div className={styles.citations}>
        <p className={styles.citationsLabel}>Cited household history</p>
        <ul className={styles.citationsList}>
          {attack.citedOutcomeIds.map((outcomeId) => (
            <li key={outcomeId} className={styles.citationChip}>
              {outcomeId}
            </li>
          ))}
        </ul>
      </div>
    </section>
  );
}
