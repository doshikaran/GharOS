import type { HTMLAttributes, ReactNode } from "react";
import styles from "./Card.module.css";

export interface CardProps extends Omit<HTMLAttributes<HTMLDivElement>, "title"> {
  /** Optional heading rendered in the display face. */
  title?: ReactNode;
  /** Raise elevation on hover — use for clickable/navigable cards only. */
  interactive?: boolean;
  children: ReactNode;
}

/**
 * GharOS design-system card — the base "page in the ledger" surface.
 * All colour comes from `styles/tokens.css`.
 */
export function Card({
  title,
  interactive = false,
  className,
  children,
  ...rest
}: CardProps) {
  const classes = [styles.card, interactive && styles.raisedOnHover, className]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={classes} {...rest}>
      {title !== undefined && <h3 className={styles.title}>{title}</h3>}
      <div className={styles.body}>{children}</div>
    </div>
  );
}
