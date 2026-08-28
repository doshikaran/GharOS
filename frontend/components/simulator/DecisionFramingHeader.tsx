import { Badge } from "@/components/design-system/Badge";
import type { DecisionFrame } from "@/lib/simulator";
import styles from "./DecisionFramingHeader.module.css";

export interface DecisionFramingHeaderProps {
  readonly frame: DecisionFrame;
}

/**
 * A35 Decision Framing's output, rendered: the question as posed, the
 * trigger that raised it, whether it was caught as a false binary, and
 * — when it was — the option(s) the naive framing left out (this phase's
 * brief: "whether it's flagged as a false binary, the unconsidered
 * option(s) surfaced").
 */
export function DecisionFramingHeader({ frame }: DecisionFramingHeaderProps) {
  return (
    <header className={styles.header} aria-label="Decision framing">
      <p className={styles.question}>{frame.question}</p>
      <p className={styles.trigger}>{frame.trigger}</p>

      <div className={styles.badgeRow}>
        {frame.isFalseBinary ? (
          <Badge variant="warning">False binary detected</Badge>
        ) : (
          <Badge variant="neutral">Not flagged as a false binary</Badge>
        )}
      </div>

      {frame.isFalseBinary && frame.unconsideredOptions.length > 0 && (
        <div className={styles.unconsidered}>
          <p className={styles.unconsideredLabel}>
            Options the binary framing left out ({frame.unconsideredOptions.length})
          </p>
          <ul className={styles.unconsideredList}>
            {frame.unconsideredOptions.map((option) => (
              <li key={option}>{option}</li>
            ))}
          </ul>
        </div>
      )}
    </header>
  );
}
