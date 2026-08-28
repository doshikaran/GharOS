"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { Badge } from "@/components/design-system/Badge";
import { NAV_ITEM_HREFS_WITH_LIVE_BADGE, NAV_SECTIONS } from "./navConfig";
import { useApprovalQueueCount } from "./useApprovalQueueCount";
import styles from "./NavSidebar.module.css";

export interface NavSidebarProps {
  /** Icon-only rail on wide viewports; hidden (off-canvas) drawer on
   * narrow ones — see `AppShell.module.css` for the two breakpoint-gated
   * meanings of this one flag. */
  collapsed: boolean;
  /** Injectable clock for the Approvals badge count, same convention as
   * `ApprovalsBoard`/`ApprovalQueue`'s own `now?: Date`; defaults to the
   * real time. */
  now?: Date;
}

/**
 * The persistent left sidebar (ADR-018) — wordmark, the two nav sections
 * in their specified order, and a footer carrying the theme switcher
 * (relocated here from being a standalone control, reusing
 * `ThemeSwitcher` unchanged) plus a small "Design system" link out to
 * `/tokens`, deliberately not a primary nav item (ADR-018 Alternative 3:
 * `/tokens` is an internal reference, not a product surface a household
 * member would visit).
 *
 * Active-route highlighting compares the current pathname to each item's
 * `href` directly (`NAV_SECTIONS` hrefs are exact route paths, not
 * prefixes) — the same pattern Next's own "Active Nav Links" doc example
 * uses (`usePathname` in a client nav component).
 */
export function NavSidebar({ collapsed, now }: NavSidebarProps) {
  const pathname = usePathname();
  const approvalCount = useApprovalQueueCount(now);

  return (
    <nav className={styles.sidebar} data-collapsed={collapsed} aria-label="Primary">
      <Link href="/" className={styles.wordmark} title="GharOS">
        <span className={styles.wordmarkMark} aria-hidden="true">
          ⌂
        </span>
        <span className={styles.wordmarkText}>GharOS</span>
      </Link>

      {NAV_SECTIONS.map((section) => (
        <div key={section.title} className={styles.section}>
          <span className={styles.sectionTitle}>{section.title}</span>
          <ul className={styles.list}>
            {section.items.map((item) => {
              const isActive = pathname === item.href;
              const Icon = item.icon;
              const showBadge = NAV_ITEM_HREFS_WITH_LIVE_BADGE.has(item.href) && approvalCount > 0;

              return (
                <li key={item.href}>
                  <Link
                    href={item.href}
                    title={item.label}
                    aria-current={isActive ? "page" : undefined}
                    aria-label={showBadge ? `${item.label}, ${approvalCount} pending approval${approvalCount === 1 ? "" : "s"}` : undefined}
                    className={`${styles.link} ${isActive ? styles.linkActive : ""}`}
                  >
                    <Icon size={18} aria-hidden="true" className={styles.icon} />
                    <span className={styles.label} aria-hidden={showBadge}>
                      {item.label}
                    </span>
                    {showBadge && (
                      <Badge variant="brass" className={styles.badge} aria-hidden="true">
                        {approvalCount}
                      </Badge>
                    )}
                  </Link>
                </li>
              );
            })}
          </ul>
        </div>
      ))}

      <div className={styles.footer}>
        <ThemeSwitcher />
        <Link href="/tokens" className={styles.designSystemLink}>
          Design system
        </Link>
      </div>
    </nav>
  );
}
