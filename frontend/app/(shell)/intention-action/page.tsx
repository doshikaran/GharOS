import type { Metadata } from "next";
import { IntentionActionExplorer } from "@/components/intention-action/IntentionActionExplorer";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./intention-action-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Intention→Action",
};

export default function IntentionActionPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Intention → Action</h1>
        <p className={styles.subheading}>
          Forgetting explains only ~10-14% of unfulfilled intentions, the rest is friction. Every blocked task
          below is diagnosed to one of six specific blocker types, with its diagnosis stated so it can be
          corrected, unblocked in a way that matches the real cause, and, when it slips repeatedly, escalated
          with real options for a human to decide.
        </p>
      </div>
      <IntentionActionExplorer baseUrl={getApiBaseUrl()} />
    </div>
  );
}
