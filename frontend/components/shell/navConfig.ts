import {
  Activity,
  CircleCheck,
  GitBranch,
  Landmark,
  Network,
  PhoneCall,
  Route,
  Scale,
  ScrollText,
  type LucideIcon,
} from "lucide-react";

/**
 * The unified shell's information architecture (ADR-018) — two sections,
 * ordered exactly as the ADR specifies: the graph first (the demo's own
 * "spine" framing, spec §5.8/Phase 6), then the thing needing attention
 * next (Approvals), then the six subsystems in build order with the
 * Household Council newly added this phase (PHASES.md Phase 12).
 *
 * This is the single source of truth for nav items: `NavSidebar` renders
 * from it directly, and `ROUTE_TITLES` below derives the top bar's
 * section title from it too, rather than either surface re-typing routes
 * or labels independently.
 */
export interface NavItem {
  readonly href: string;
  readonly label: string;
  readonly icon: LucideIcon;
}

export interface NavSection {
  readonly title: string;
  readonly items: readonly NavItem[];
}

export const NAV_SECTIONS: readonly NavSection[] = [
  {
    title: "Overview",
    items: [
      { href: "/graph", label: "Household Graph", icon: Network },
      { href: "/approvals", label: "Approvals", icon: CircleCheck },
      { href: "/status", label: "System Status", icon: Activity },
    ],
  },
  {
    title: "Subsystems",
    items: [
      { href: "/ledger", label: "Household Ledger", icon: ScrollText },
      { href: "/fair-allocator", label: "Fair Allocator", icon: Scale },
      { href: "/intention-action", label: "Intention → Action", icon: Route },
      { href: "/concierge", label: "Outbound Concierge", icon: PhoneCall },
      { href: "/simulator", label: "Household Simulator", icon: GitBranch },
      { href: "/council", label: "Household Council", icon: Landmark },
    ],
  },
] as const;

/** Only the `/approvals` nav item carries the live pending-count badge
 * (ADR-018) — a `Set` rather than a per-item boolean field, since it is
 * the one cross-cutting exception to an otherwise uniform nav item shape. */
export const NAV_ITEM_HREFS_WITH_LIVE_BADGE: ReadonlySet<string> = new Set(["/approvals"]);

/**
 * Route → section title shown in the top bar (ADR-018: "a small static
 * route→title map, not string manipulation on the pathname"), derived
 * once from `NAV_SECTIONS` rather than re-typed by hand.
 */
export const ROUTE_TITLES: ReadonlyMap<string, string> = new Map(
  NAV_SECTIONS.flatMap((section) => section.items.map((item) => [item.href, item.label] as const)),
);

/** Shown for `/` (the home page) and any route the map above doesn't name. */
export const DEFAULT_ROUTE_TITLE = "GharOS";

export function titleForRoute(pathname: string): string {
  return ROUTE_TITLES.get(pathname) ?? DEFAULT_ROUTE_TITLE;
}
