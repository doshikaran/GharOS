import type { ReactNode } from "react";
import styles from "./Toggle.module.css";

export interface ToggleProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label?: ReactNode;
  disabled?: boolean;
  className?: string;
}

/**
 * GharOS design-system toggle switch. Built on a native `<button
 * role="switch">` (not a styled checkbox) so keyboard and screen-reader
 * behaviour come for free and stay correct as styling changes.
 */
export function Toggle({ checked, onChange, label, disabled = false, className }: ToggleProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      disabled={disabled}
      data-disabled={disabled}
      className={[styles.wrapper, className].filter(Boolean).join(" ")}
      onClick={() => !disabled && onChange(!checked)}
    >
      <span className={styles.track} data-checked={checked}>
        <span className={styles.thumb} />
      </span>
      {label !== undefined && <span className={styles.label}>{label}</span>}
    </button>
  );
}
