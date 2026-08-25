"use client";

import { useState } from "react";
import { Button } from "@/components/design-system/Button";
import { Dialog } from "@/components/design-system/Dialog";
import { isEscalation, isResolved, needsApproval, type ApprovalQueueItem } from "@/lib/approvals";
import { ApprovalQueue } from "./ApprovalQueue";
import { EscalationSurface } from "./EscalationSurface";
import { EvidenceBundleView } from "./EvidenceBundleView";
import { RiskTierBadge } from "./RiskTierBadge";
import styles from "./ApprovalsBoard.module.css";

export interface ApprovalsBoardProps {
  initialItems: ApprovalQueueItem[];
  /** Injectable clock for deterministic tests; defaults to the real time. */
  now?: Date;
}

/**
 * Stateful orchestrator for the `/approvals` page — a client component
 * (local state + confirm dialog) deliberately kept separate from
 * `app/approvals/page.tsx`, which stays a Server Component so it can
 * export page `metadata` (same split as `StatusBoard`/`app/status/page.tsx`).
 *
 * Owns the one interaction spec §18.2's demo requirement is entirely
 * about: clicking Approve on a queued item never executes anything by
 * itself — it opens a confirm dialog restating the full evidence bundle,
 * and only an explicit "Confirm and execute" inside that dialog does
 * anything. Closing the dialog any other way (Escape, backdrop click, the
 * × button) cancels — never implies consent (see `Dialog`'s own doc
 * comment). This is what makes "never show the agent spending money or
 * placing a call without a visible confirm" true in this surface, not
 * just documented as a policy.
 */
export function ApprovalsBoard({ initialItems, now }: ApprovalsBoardProps) {
  const clock = now ?? new Date();
  const [items, setItems] = useState<ApprovalQueueItem[]>(initialItems);
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [discussedIds, setDiscussedIds] = useState<ReadonlySet<string>>(new Set());

  const confirmingItem = confirmingId ? (items.find((item) => item.id === confirmingId) ?? null) : null;

  function handleApproveClick(id: string) {
    setConfirmingId(id);
  }

  function handleReject(id: string) {
    setItems((prev) => prev.map((item) => (item.id === id ? { ...item, status: "rejected" } : item)));
  }

  function handleConfirmApproval() {
    if (!confirmingId) return;
    setItems((prev) =>
      prev.map((item) => (item.id === confirmingId ? { ...item, status: "approved" } : item)),
    );
    setConfirmingId(null);
  }

  function handleCancelApproval() {
    setConfirmingId(null);
  }

  function handleToggleDiscussed(id: string, discussed: boolean) {
    setDiscussedIds((prev) => {
      const next = new Set(prev);
      if (discussed) {
        next.add(id);
      } else {
        next.delete(id);
      }
      return next;
    });
  }

  const pendingCount = items.filter((item) => needsApproval(item, clock)).length;
  const escalatedCount = items.filter((item) => isEscalation(item, clock)).length;
  const resolvedCount = items.filter((item) => isResolved(item, clock)).length;

  return (
    <div className={styles.board}>
      <p className={styles.summary} role="status" aria-live="polite">
        {pendingCount} need your decision · {escalatedCount} escalated · {resolvedCount} resolved
      </p>

      <section aria-label="Approval queue">
        <h2 className={styles.groupHeading}>Approval queue</h2>
        <ApprovalQueue items={items} onApprove={handleApproveClick} onReject={handleReject} now={clock} />
      </section>

      <section aria-label="Escalation surface">
        <h2 className={styles.groupHeading}>Escalation surface</h2>
        <p className={styles.groupIntro}>
          What GharOS declines to decide for you, and why — the raw evidence and its own reasoning for not
          resolving this, never a synthesized recommendation and never a silent default (spec §7.7, §18.1).
        </p>
        <EscalationSurface
          items={items}
          now={clock}
          discussedIds={discussedIds}
          onToggleDiscussed={handleToggleDiscussed}
        />
      </section>

      <Dialog
        open={confirmingItem !== null}
        onClose={handleCancelApproval}
        title="Confirm approval — this executes now"
      >
        {confirmingItem && (
          <div className={styles.confirmBody}>
            <p className={styles.confirmAction}>{confirmingItem.proposedActionSummary}</p>
            <RiskTierBadge tier={confirmingItem.riskTier} />
            <EvidenceBundleView bundle={confirmingItem.evidenceBundle} />
            <p className={styles.confirmWarning} role="alert">
              Approving now executes this action immediately — there is no further confirmation after this
              one.
            </p>
            <div className={styles.confirmActions}>
              <Button variant="secondary" onClick={handleCancelApproval}>
                Cancel
              </Button>
              <Button variant="primary" onClick={handleConfirmApproval}>
                Confirm and execute
              </Button>
            </div>
          </div>
        )}
      </Dialog>
    </div>
  );
}
