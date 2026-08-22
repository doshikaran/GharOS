"use client";

import { useEffect, useState } from "react";
import { useTheme } from "next-themes";
import { Monitor, Moon, Sun } from "lucide-react";
import styles from "./ThemeSwitcher.module.css";

const OPTIONS = [
  { value: "light", label: "Light", Icon: Sun },
  { value: "dark", label: "Dark", Icon: Moon },
  { value: "system", label: "System", Icon: Monitor },
] as const;

/**
 * Light / dark / system switcher built on `next-themes`. Renders nothing
 * theme-dependent until mounted, to avoid a hydration mismatch — the
 * flash-of-wrong-theme itself is already prevented at the `<html>` level
 * by `suppressHydrationWarning` plus next-themes' injected pre-hydration
 * script (see app/layout.tsx).
 */
export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);

  // Documented next-themes pattern: `theme` differs between the server
  // render and the first client render, so theme-dependent output is
  // deferred one tick past mount to avoid a hydration mismatch.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setMounted(true), []);

  return (
    <div className={styles.group} role="radiogroup" aria-label="Colour theme">
      {OPTIONS.map(({ value, label, Icon }) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={mounted && theme === value}
          data-active={mounted && theme === value}
          className={styles.option}
          onClick={() => setTheme(value)}
        >
          <Icon size={16} aria-hidden="true" />
          {label}
        </button>
      ))}
    </div>
  );
}
