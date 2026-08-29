import type { ReactNode } from "react";
import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { EvidenceBundleView } from "@/components/approvals/EvidenceBundleView";
import { RiskTierBadge } from "@/components/approvals/RiskTierBadge";
import { formatDateTime } from "@/lib/approvals";
import type { FallbackDecision } from "@/lib/concierge";
import styles from "./ConciergeFallbackSurface.module.css";

export interface ConciergeFallbackSurfaceProps {
  readonly title: string;
  readonly decision: FallbackDecision;
}

/**
 * Renders A56's real `FallbackDecision` (this phase's brief item 5),
 * reusing the same escalation visual/interaction language every prior
 * phase already established (`components/approvals/EscalationSurface`,
 * `components/intention-action/SlippageEscalationSurface`) rather than
 * inventing a fourth look: a card, a risk-tier badge, the full evidence
 * bundle, and — critically — no resolve/approve button anywhere on the
 * `escalate` branch. Presenting the options is the whole job; a human
 * decides.
 *
 * `retry` renders the real `retryAfter` time plainly, distinct from
 * `escalate`'s full brief — the two states are never visually conflated.
 */
export function ConciergeFallbackSurface({ title, decision }: ConciergeFallbackSurfaceProps) {
  if (decision.action === "retry") {
    return (
      <Card className={styles.card} title={<TitleRow title={title} badge={<Badge variant="info">Retrying</Badge>} />}>
        <p className={styles.reasoning}>{decision.reasoning}</p>
        {decision.retryAfter && (
          <p className={styles.retryLine} role="status">
            Next attempt authorised at <strong>{formatDateTime(decision.retryAfter)}</strong>, not before.
          </p>
        )}
      </Card>
    );
  }

  if (decision.action === "web_booking_fallback") {
    return (
      <Card className={styles.card} title={<TitleRow title={title} badge={<Badge variant="brass">Web fallback</Badge>} />}>
        <p className={styles.reasoning}>{decision.reasoning}</p>
      </Card>
    );
  }

  const payload = decision.escalationPayload;
  return (
    <Card className={styles.card} title={<TitleRow title={title} badge={<Badge variant="warning">Escalated, a human decides</Badge>} />}>
      <p className={styles.reasoning}>{decision.reasoning}</p>
      {payload && (
        <>
          <RiskTierBadge tier={payload.riskTier} />
          <p className={styles.summary}>{payload.summary}</p>
          <EvidenceBundleView bundle={payload.evidenceBundle} />
          <p className={styles.framingNote}>
            Presenting options for a household member to decide, this surface never resolves the call itself,
            and never re-tries automatically once it reaches this point.
          </p>
        </>
      )}
    </Card>
  );
}

function TitleRow({ title, badge }: { title: string; badge: ReactNode }) {
  return (
    <span className={styles.titleRow}>
      <span>{title}</span>
      {badge}
    </span>
  );
}
