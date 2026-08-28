"use client";

import { useState } from "react";
import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import { EvidenceBundleView } from "@/components/approvals/EvidenceBundleView";
import { RiskTierBadge } from "@/components/approvals/RiskTierBadge";
import type { ConciergeCallApproval } from "@/lib/concierge";
import styles from "./CallApprovalGate.module.css";

export interface CallApprovalGateProps {
  readonly approval: ConciergeCallApproval;
  /** Whether a human has approved this call yet. Purely local UI state —
   * there is no live write endpoint this phase, matching every prior
   * phase's fixture-seam precedent. */
  approved: boolean;
  onApprove: () => void;
}

/**
 * Spec §13.2 Step 4's "R2/R3 gate" (this phase's brief item 2's approval
 * requirement, and `.claude/agents/e4.md`'s own "never do": "let a screen
 * show... a call being placed without a visible approval step"). Renders
 * the full evidence bundle exactly like the Phase 5 Approval Gate
 * (`ApprovalCard`/`EvidenceBundleView`) — reused, not reinvented — and
 * offers exactly one affirmative action. There is no path in this
 * component that reveals a call transcript before `approved` is true;
 * the caller (`ConciergeExplorer`) enforces that ordering.
 */
export function CallApprovalGate({ approval, approved, onApprove }: CallApprovalGateProps) {
  const [justApproved, setJustApproved] = useState(false);

  function handleApprove() {
    onApprove();
    setJustApproved(true);
  }

  return (
    <Card
      className={styles.card}
      title={
        <span className={styles.titleRow}>
          <span>{approval.evidenceBundle.proposedAction}</span>
          {approved ? <Badge variant="success">Approved</Badge> : <Badge variant="warning">Awaiting decision</Badge>}
        </span>
      }
    >
      <div className={styles.body}>
        <p className={styles.gateLabel}>Approval — before any call is placed</p>
        <RiskTierBadge tier={approval.riskTier} />
        <EvidenceBundleView bundle={approval.evidenceBundle} />

        {!approved ? (
          <div className={styles.actions}>
            <Button variant="primary" onClick={handleApprove}>
              Approve this call
            </Button>
          </div>
        ) : (
          <p className={styles.approvedNote} role="status">
            {justApproved ? "Approved just now — " : "Approved — "}
            the call below only happened because this was confirmed first.
          </p>
        )}
      </div>
    </Card>
  );
}
