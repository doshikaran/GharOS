import { Badge, type BadgeVariant } from "@/components/design-system/Badge";
import { RISK_TIER_POLICY, type RiskTier } from "@/lib/approvals";
import styles from "./RiskTierBadge.module.css";

export interface RiskTierBadgeProps {
  tier: RiskTier;
  className?: string;
}

const VARIANT: Record<RiskTier, BadgeVariant> = {
  R0: "success",
  R1: "info",
  R2: "warning",
  R3: "danger",
  // R4 gets its own visual register deliberately — it is not "just worse
  // than R3," it is a structurally different policy (never auto-executes,
  // escalate only), and it must never blend into the danger/warning ramp
  // the other four tiers share.
  R4: "royal",
};

/**
 * Renders a risk tier as a code AND its real policy meaning — spec §18.1's
 * whole point is that a household member (or a judge) should never have to
 * memorise what "R3" means. Used by both the approval queue and the
 * escalation surface so the encoding is learned once.
 */
export function RiskTierBadge({ tier, className }: RiskTierBadgeProps) {
  const entry = RISK_TIER_POLICY[tier];
  return (
    <span className={[styles.wrapper, className].filter(Boolean).join(" ")}>
      <Badge variant={VARIANT[tier]}>{entry.label}</Badge>
      <span className={styles.meaning}>
        {entry.definition} {entry.policy}
      </span>
    </span>
  );
}
