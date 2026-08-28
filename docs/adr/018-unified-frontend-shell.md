# ADR-018: Unified frontend navigation shell — persistent sidebar, one product instead of eight pages

**Status:** accepted
**Phase:** 11
**Date:** 2026-08-28
**Decision authority:** delegated to the CTO by the operator explicitly this phase ("you get the authority here to decide the flow and to connect them... take the call").

## Context

By Phase 10's gate, the frontend had grown to eight independent route trees (`/graph`, `/ledger`, `/fair-allocator`, `/intention-action`, `/concierge`, `/approvals`, `/status`, `/tokens`) plus a home page, each a self-contained `page.tsx` with no shared chrome. `frontend/app/layout.tsx` is currently minimal — fonts and `ThemeProvider` only, no navigation. Each subsystem is real and independently gated, but nothing connects them into one product a person (or a judge) can move through without knowing eight URLs by heart. This is a real, user-visible gap, not a cosmetic one: GharOS's own premise is a single household operating system, and the demo (Phase 15) will be judged as one continuous experience, not eight demos back to back.

## Decision

**A persistent left sidebar + slim top bar, added once at the root layout, wrapping every route except `/tokens`.**

### Information architecture

Two grouped sections in the sidebar, ordered by how a household member actually uses the system — the graph first (the spine, and Phase 6's own framing as "the demo's spine"), the thing needing attention next (Approvals), then the five subsystems in build order, Simulator newly added:

```
GharOS  [logo/wordmark]
─────────────────────
OVERVIEW
  ◆ Household Graph        /graph
  ◆ Approvals         (●3) /approvals    <- live pending-count badge
  ◆ System Status           /status

SUBSYSTEMS
  ◆ Household Ledger        /ledger
  ◆ Fair Allocator          /fair-allocator
  ◆ Intention → Action      /intention-action
  ◆ Outbound Concierge      /concierge
  ◆ Household Simulator     /simulator      <- new this phase
─────────────────────
  ☾ Theme                          [toggle, bottom of rail]
```

- **`/approvals`'s badge is live**, sourced from the same data `/approvals` itself renders (a small shared hook, `useApprovalQueueCount()`, reading `/graph/snapshot` and counting `PENDING` `ApprovalRequest`s client-side) — not a second, drifting source of truth. This is the single highest-signal cross-cutting indicator in an autonomous household system ("what does it want me to sign off on right now") and belongs in the shell precisely because it must be visible from every surface, not just its own page.
- **`/tokens`** (the design-system reference page, Phase 0.D) is deliberately **excluded** from the shell — it is an internal engineering reference, not a product surface, and wrapping it in product chrome would misrepresent it as one. It stays reachable directly by URL, linked only from a small "design system" footer link inside the shell itself, not a primary nav item.
- **Collapsible on narrow viewports** (a hamburger toggle collapses the rail to icons-only, then to an overlay drawer below a documented breakpoint) — the graph view and several subsystem views (fair-allocator's cost matrix, the live transcript view) are wide-content surfaces; the shell must not steal horizontal space from them on a demo laptop's 13" screen without an explicit choice to collapse it.
- **Section title in the top bar** derives from the active route (a small static route→title map, not string manipulation on the pathname) so every page reads as part of one product even though each page's own internal heading is unchanged.

### Implementation shape (E4 owns all of it — no cross-boundary edits)

- `frontend/components/shell/AppShell.tsx` — the sidebar + top bar + `{children}` slot.
- `frontend/components/shell/NavSidebar.tsx`, `TopBar.tsx`, `useApprovalQueueCount.ts` (co-located hook).
- `frontend/app/layout.tsx` wraps `{children}` in `<AppShell>` for every route; `/tokens/page.tsx` is the one page that opts out (Next's route-group mechanism — `(shell)` vs a bare group for `/tokens` — is the intended tool for this; E4 confirms the exact App Router convention against `node_modules/next/dist/docs/` per this repo's own `AGENTS.md` warning before implementing, rather than assuming an older Next.js API).
- Each existing page's own top-level heading/padding is reviewed (not rewritten) so nothing doubles up visually once nested inside the shell's content area — a chrome-nesting pass, not a content rewrite. No subsystem's business logic, data-fetching, or test files change as part of this ADR.

## Alternatives considered

1. **A top nav bar only (no sidebar).** Rejected — eight-plus destinations do not fit legibly in a single horizontal bar without a dropdown, and a dropdown re-hides the exact "one product, not eight secrets" problem this ADR exists to fix.
2. **A command-palette / search-first nav (no persistent visible list).** Rejected for a judged demo specifically — a judge (or the operator, rehearsing) needs to *see* the full breadth of what was built at a glance; hiding it behind a keystroke undersells real, working scope.
3. **Wrapping `/tokens` in the shell too, for consistency.** Rejected — `/tokens` is not a place a household member would ever go; presenting it as a nav-level peer of `/ledger` would misstate what it is.

## Consequences

One new `frontend/components/shell/` directory (E4). `frontend/app/layout.tsx` changes (E4-owned file). No backend contract, no new API surface beyond what `/approvals` already exposes. Every existing page keeps its own tests unchanged; new tests cover `AppShell`'s nav rendering, active-route highlighting, the live badge count, and the collapse behaviour. This is additive chrome around seven already-gated subsystems plus the new eighth (`/simulator`, this phase) — it does not reopen any prior phase's gate.
