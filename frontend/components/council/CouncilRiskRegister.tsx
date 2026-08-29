import styles from "./CouncilRiskRegister.module.css";

export interface CouncilRiskRegisterProps {
  readonly entries: readonly string[];
}

/** A flat, scannable list — `CouncilBrief.riskRegister` is already a
 * plain string list (unlike the Simulator's categorised register), so
 * this component adds no structure the data doesn't have. */
export function CouncilRiskRegister({ entries }: CouncilRiskRegisterProps) {
  if (entries.length === 0) {
    return <p className={styles.empty}>No risks raised on this brief.</p>;
  }

  return (
    <ul className={styles.list} aria-label="Risk register">
      {entries.map((entry) => (
        <li key={entry} className={styles.row}>
          {entry}
        </li>
      ))}
    </ul>
  );
}
