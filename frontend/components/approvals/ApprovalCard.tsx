import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import {
  RISK_TIER_POLICY,
  formatDateTime,
  isExpired,
  needsApproval,
  type ApprovalQueueItem,
} from "@/lib/approvals";
import { EvidenceBundleView } from "./EvidenceBundleView";
import { RiskTierBadge } from "./RiskTierBadge";
import styles from "./ApprovalCard.module.css";

export interface ApprovalCardProps {
  item: ApprovalQueueItem;
  onApprove?: (id: string) => void;
  onReject?: (id: string) => void;
  /** Injectable clock for deterministic tests; defaults to the real time. */
  now?: Date;
}

/**
 * One item in the approve/reject queue. Renders the complete evidence
 * bundle (spec §18.2 — "every approval request carries: proposed action,
 * reasoning, evidence consulted, confidence, consequence-if-wrong") and
 * the risk tier's real policy meaning, then offers Approve/Reject only
 * when the item genuinely still needs a human decision.
 *
 * Defends its own affordances rather than trusting the caller to filter
 * correctly: an R4 item never gets Approve/Reject here (R4 "never
 * auto-executes" — spec §18.1 — it belongs on `EscalationSurface`
 * instead), and an item whose approval window has passed renders as
 * escalated, visibly and distinctly, never as pending and never as
 * approved (spec §18.2 — "approval expiry escalates; never auto-approves").
 */
export function ApprovalCard({ item, onApprove, onReject, now }: ApprovalCardProps) {
  const clock = now ?? new Date();
  const actionable = needsApproval(item, clock);
  const expired = isExpired(item, clock);

  return (
    <Card
      className={styles.card}
      title={
        <span className={styles.titleRow}>
          <span>{item.proposedActionSummary}</span>
          <StatusBadge item={item} expired={expired} />
        </span>
      }
    >
      <div className={styles.body}>
        <RiskTierBadge tier={item.riskTier} />
        <EvidenceBundleView bundle={item.evidenceBundle} />

        {actionable && (
          <p className={styles.expiry}>
            Approval window closes <strong>{formatDateTime(item.expiresAt)}</strong>. If no decision arrives
            by then, this escalates automatically — it will never auto-approve.
          </p>
        )}

        {actionable && (
          <div className={styles.actions}>
            <Button variant="secondary" onClick={() => onReject?.(item.id)}>
              Reject
            </Button>
            <Button variant="primary" onClick={() => onApprove?.(item.id)}>
              Approve
            </Button>
          </div>
        )}

        {!actionable && expired && (
          <p className={styles.escalatedNote} role="status">
            This request&apos;s approval window closed at {formatDateTime(item.expiresAt)} with no decision.
            It has escalated — see the escalation surface below. It is not, and has never been, approved.
          </p>
        )}

        {!actionable && !expired && <ResolvedNote item={item} />}
      </div>
    </Card>
  );
}

function StatusBadge({ item, expired }: { item: ApprovalQueueItem; expired: boolean }) {
  if (expired) {
    return <Badge variant="warning">Escalated</Badge>;
  }
  if (item.status === "pending") {
    return <Badge variant="info">Awaiting decision</Badge>;
  }
  if (item.status === "approved") {
    return <Badge variant="success">Approved</Badge>;
  }
  return <Badge variant="neutral">Rejected</Badge>;
}

function ResolvedNote({ item }: { item: ApprovalQueueItem }) {
  const autoCleared = item.riskTier === "R0" || item.riskTier === "R1";
  if (autoCleared && item.status === "approved") {
    return (
      <p className={styles.resolvedNote}>
        Cleared automatically under {RISK_TIER_POLICY[item.riskTier].label} policy — no human approval was
        requested or required. Shown here for visibility into the tiering system.
      </p>
    );
  }
  if (item.status === "approved") {
    return <p className={styles.resolvedNote}>Approved by a household member.</p>;
  }
  return <p className={styles.resolvedNote}>Rejected by a household member.</p>;
}
