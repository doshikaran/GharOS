import { AppShell } from "@/components/shell/AppShell";

/**
 * Nested layout for the `(shell)` route group (ADR-018) — wraps every
 * page under it (`/graph`, `/approvals`, `/status`, `/ledger`,
 * `/fair-allocator`, `/intention-action`, `/concierge`, `/simulator`,
 * `/council`, `/voice`, and `/story`) in the persistent app shell. `/`
 * itself moved OUT of this group in the 2026-08-29 private-bank pass:
 * the standalone landing lives in `app/(landing)/` with its own minimal
 * layout (no AppShell), and the old narrative landing this group used to
 * serve at `/` now lives on at `/story` (deliberately not in the
 * sidebar; reachable from the landing's footer). This is a nested layout,
 * not a root layout — `app/layout.tsx` above it still owns `<html>`,
 * `<body>`, fonts, and `ThemeProvider` (see Next's layout convention:
 * "any layout without a `layout.js` above it is a root layout" — this
 * one has `app/layout.tsx` above it, so it is not one).
 *
 * `app/tokens/page.tsx` sits outside `(shell)` entirely and therefore
 * never renders `AppShell` — the design-system reference page stays
 * unwrapped in product chrome, per ADR-018's explicit exclusion.
 *
 * Typed as `LayoutProps<"/">`, not `LayoutProps<"/(shell)">`: route
 * groups add no URL segment, so Next's generated `.next/types/routes.d.ts`
 * only ever emits `"/"` as a `LayoutRoutes` member here — confirmed by
 * building once and reading the generated file, per this repo's own
 * `AGENTS.md` instruction not to assume an older API.
 */
export default function ShellLayout({ children }: LayoutProps<"/">) {
  return <AppShell>{children}</AppShell>;
}
