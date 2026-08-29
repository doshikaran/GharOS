import Link from "next/link";
import styles from "./landing-layout.module.css";

/**
 * Nested layout for the `(landing)` route group (2026-08-29 private-bank
 * pass) — serves `/` only. Deliberately does NOT render `AppShell`: no
 * sidebar, no top bar, just a minimal header (wordmark left, "Open app"
 * right). `app/layout.tsx` above it still owns `<html>`, `<body>`,
 * fonts, and `ThemeProvider` — route groups add no URL segment and this
 * layout has a parent, so it is a nested layout, not a root layout
 * (verified against `node_modules/next/dist/docs/01-app/03-api-reference/
 * 03-file-conventions/route-groups.md`; the old `/` page moved to
 * `app/(shell)/story/`, so no two groups resolve the same path).
 *
 * Typed `LayoutProps<"/">` for the same reason `app/(shell)/layout.tsx`
 * documents: route groups add no URL segment, so the generated
 * `LayoutRoutes` member here is `"/"`.
 */
export default function LandingLayout({ children }: LayoutProps<"/">) {
  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <Link href="/" className={styles.wordmark}>
          GharOS
        </Link>
        <Link href="/graph" className={styles.openApp}>
          Open app
        </Link>
      </header>
      <main className={styles.main}>{children}</main>
    </div>
  );
}
