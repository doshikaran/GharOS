import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { Toggle } from "@/components/design-system/Toggle";
import { formatDateTime, isExpired, type ApprovalQueueItem } from "@/lib/approvals";
import { EvidenceBundleView } from "./EvidenceBundleView";
import { RiskTierBadge } from "./RiskTierBadge";
import styles from "./EscalationCard.module.css";

export interface EscalationCardProps {
  item: ApprovalQueueItem;
  /** Injectable clock for deterministic tests; defaults to the real time. */
  now?: Date;
  /** Whether the household has marked this brief as discussed. Purely a
   * local tracking affordance — never an approval or an execution. */
  discussed?: boolean;
  onToggleDiscussed?: (id: string, discussed: boolean) => void;
}

/**
 * One item on the escalation surface — genuinely different treatment from
 * `ApprovalCard`, not a relabelled approve/reject item (this phase's brief).
 *
 * Two, non-exclusive reasons an item lands here:
 *   - **R4 — escalate only** (spec §18.1): "never auto-execute; present
 *     options only." The Council does not resolve this tier — "it produces
 *     a brief; humans decide" (spec §18.2). There is no Approve/Reject
 *     here, ever, for any R4 item, at any status — that would misrepresent
 *     what this tier means.
 *   - **Expired** (spec §18.2): "approval expiry escalates; never
 *     auto-approves." An expired request is not a rejected one and not a
 *     pending one — it is a decision that still needs to be made, just
 *     without automation's help.
 *
 * The only interactive affordance here is a "discussed with the
 * household" toggle — explicitly documented in its own copy as tracking,
 * not approval, so it can never be mistaken for the queue's Approve button.
 */
export function EscalationCard({ item, now, discussed = false, onToggleDiscussed }: EscalationCardProps) {
  const clock = now ?? new Date();
  const expired = isExpired(item, clock);
  const isCouncilBrief = item.riskTier === "R4";

  return (
    <Card
      className={styles.card}
      title={
        <span className={styles.titleRow}>
          <span>{item.proposedActionSummary}</span>
        </span>
      }
    >
      <div className={styles.body}>
        <div className={styles.reasons}>
          {isCouncilBrief && (
            <Badge variant="royal">Council brief — humans decide</Badge>
          )}
          {expired && <Badge variant="warning">Escalated — approval window expired</Badge>}
        </div>

        <RiskTierBadge tier={item.riskTier} />

        <p className={styles.explainer}>
          {isCouncilBrief
            ? "This category is irreversible, high-stakes, and emotionally loaded for the household. GharOS never auto-executes it and the Council never resolves it — the brief below lays out the reasoning and evidence for a human decision, not a synthesized recommendation."
            : `This request's approval window closed at ${formatDateTime(
                item.expiresAt,
              )} with no decision from a human. It has not been approved, and it has not been rejected — it needs a decision now.`}
        </p>

        <EvidenceBundleView bundle={item.evidenceBundle} />

        <div className={styles.discussedRow}>
          <Toggle
            checked={discussed}
            onChange={(checked) => onToggleDiscussed?.(item.id, checked)}
            label="Discussed with the household"
          />
          <p className={styles.discussedNote}>
            This only tracks whether the household has talked this through — it does not approve, reject, or
            execute anything.
          </p>
        </div>
      </div>
    </Card>
  );
}
