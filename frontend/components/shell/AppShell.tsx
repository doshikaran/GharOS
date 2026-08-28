"use client";

import { useState, type ReactNode } from "react";
import { NavSidebar } from "./NavSidebar";
import { TopBar } from "./TopBar";
import styles from "./AppShell.module.css";

export interface AppShellProps {
  children: ReactNode;
}

/**
 * Root chrome for every route inside `app/(shell)/` (ADR-018) — persistent
 * left sidebar, slim top bar, `{children}` in a scrollable content region.
 * Wired in once, at `app/(shell)/layout.tsx`; `/tokens` lives outside that
 * route group and never renders this component.
 *
 * Collapse state is a single boolean, toggled from `TopBar`'s hamburger,
 * read by CSS at two different breakpoints (`AppShell.module.css`):
 *
 *   - Above 960px (the same collapse breakpoint `GraphExplorer` already
 *     uses, kept consistent rather than inventing a second one): toggles
 *     the sidebar between full width and an icon-only rail.
 *   - At or below 960px: toggles the sidebar between off-canvas (hidden)
 *     and an overlay drawer with a click-to-dismiss backdrop.
 *
 * One flag, one toggle — the visual difference between "icon rail" and
 * "overlay drawer" is expressed entirely in CSS media queries, not a
 * second JS viewport check, so there is exactly one source of truth for
 * "is the nav open."
 */
export function AppShell({ children }: AppShellProps) {
  const [collapsed, setCollapsed] = useState(false);

  return (
    <div className={styles.shell} data-collapsed={collapsed}>
      <NavSidebar collapsed={collapsed} />
      {/* Narrow-viewport-only backdrop: `display: none` above the
          breakpoint (see AppShell.module.css) means this never intercepts
          clicks on a wide viewport, collapsed or not. */}
      <button
        type="button"
        className={styles.backdrop}
        aria-hidden="true"
        tabIndex={-1}
        onClick={() => setCollapsed(true)}
      />
      <div className={styles.content}>
        <TopBar collapsed={collapsed} onToggleCollapse={() => setCollapsed((prev) => !prev)} />
        <main className={styles.main}>{children}</main>
      </div>
    </div>
  );
}
