import type { HTMLAttributes, ReactNode } from "react";
import styles from "./Badge.module.css";

export type BadgeVariant =
  | "neutral"
  | "royal"
  | "brass"
  | "success"
  | "warning"
  | "danger"
  | "info";

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  variant?: BadgeVariant;
  children: ReactNode;
}

const VARIANT_CLASS: Record<BadgeVariant, string> = {
  neutral: styles.neutral,
  royal: styles.royal,
  brass: styles.brass,
  success: styles.success,
  warning: styles.warning,
  danger: styles.danger,
  info: styles.info,
};

/**
 * General-purpose status pill. For the extracted/inferred/ambiguous
 * derivation marker used across the graph and provenance UI, use
 * `DerivationBadge` instead — that encoding is load-bearing, not
 * decorative, and must not be improvised per-screen with this component.
 */
export function Badge({ variant = "neutral", className, children, ...rest }: BadgeProps) {
  const classes = [styles.badge, VARIANT_CLASS[variant], className]
    .filter(Boolean)
    .join(" ");

  return (
    <span className={classes} {...rest}>
      {children}
    </span>
  );
}
