import { CalendarClock, Footprints, GitFork, Info, Link2, PhoneOff, type LucideIcon } from "lucide-react";
import type { BadgeVariant } from "@/components/design-system/Badge";
import type { BlockerType } from "@/lib/intention-action";

/**
 * The six-type taxonomy's real, distinct visual encoding (this phase's
 * brief item 3: "not just a text label") — one icon plus one `Badge`
 * variant per type, exactly the count of non-neutral `Badge` variants
 * (`royal`/`brass`/`success`/`warning`/`danger`/`info`), so every type gets
 * a genuinely different colour, never a re-used one. The icon is the
 * accessibility-safe half of the encoding (mirrors `DerivationBadge`'s
 * dot-plus-border-style precedent): colour alone is never the only signal.
 */
export const BLOCKER_TYPE_VARIANT: Readonly<Record<BlockerType, BadgeVariant>> = {
  information: "info",
  decision: "royal",
  window: "warning",
  first_step_ambiguity: "brass",
  dependency: "success",
  aversion: "danger",
};

export const BLOCKER_TYPE_ICON: Readonly<Record<BlockerType, LucideIcon>> = {
  information: Info,
  decision: GitFork,
  window: CalendarClock,
  first_step_ambiguity: Footprints,
  dependency: Link2,
  aversion: PhoneOff,
};
