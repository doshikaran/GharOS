import type { Metadata } from "next";
import { ApprovalsBoard } from "@/components/approvals/ApprovalsBoard";
import { getApprovalQueue } from "@/lib/approvals";
import styles from "./approvals-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Approval queue",
};

export default function ApprovalsPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Approval queue</h1>
        <p className={styles.subheading}>
          Every action GharOS proposes above R1 stops here first. Each request below carries its full
          evidence bundle, the proposed
          action, the reasoning, every piece of evidence consulted, a confidence score, and what happens if
          it&apos;s wrong, never a summary hiding the rest. An approval window that closes without a
          decision escalates; it never auto-approves. The <code>R4</code> tier is never offered here at all,
          it moves straight to the escalation surface below, where the Council presents a brief rather than a
          decision.
        </p>
      </div>
      <ApprovalsBoard initialItems={getApprovalQueue()} />
    </div>
  );
}
