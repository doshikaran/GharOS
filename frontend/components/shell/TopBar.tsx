"use client";

import { usePathname } from "next/navigation";
import { Menu } from "lucide-react";
import { titleForRoute } from "./navConfig";
import styles from "./TopBar.module.css";

export interface TopBarProps {
  collapsed: boolean;
  onToggleCollapse: () => void;
}

/**
 * Slim top bar (ADR-018) — a hamburger toggle for the sidebar (icon-rail
 * on wide viewports, overlay drawer below the documented breakpoint; see
 * `AppShell.module.css`) and a section title derived from the active
 * route via a small static `pathname -> title` map (`titleForRoute`),
 * never string manipulation on the pathname itself.
 */
export function TopBar({ collapsed, onToggleCollapse }: TopBarProps) {
  const pathname = usePathname();
  const title = titleForRoute(pathname);

  return (
    <header className={styles.topBar}>
      <button
        type="button"
        className={styles.toggle}
        onClick={onToggleCollapse}
        aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        aria-expanded={!collapsed}
      >
        <Menu size={20} aria-hidden="true" />
      </button>
      <h1 className={styles.title}>{title}</h1>
    </header>
  );
}
