import type { ButtonHTMLAttributes, ReactNode } from "react";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "brass" | "secondary" | "danger" | "ghost";

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  /** Visual style. Defaults to "primary" (royal fill). */
  variant?: ButtonVariant;
  children: ReactNode;
}

const VARIANT_CLASS: Record<ButtonVariant, string> = {
  primary: styles.primary,
  brass: styles.brass,
  secondary: styles.secondary,
  danger: styles.danger,
  ghost: styles.ghost,
};

/**
 * GharOS design-system button. All colour comes from CSS custom properties
 * defined in `styles/tokens.css` — never a raw hex value.
 */
export function Button({
  variant = "primary",
  className,
  type = "button",
  ...rest
}: ButtonProps) {
  const classes = [styles.button, VARIANT_CLASS[variant], className]
    .filter(Boolean)
    .join(" ");

  return <button type={type} className={classes} {...rest} />;
}
