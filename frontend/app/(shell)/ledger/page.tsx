import type { Metadata } from "next";
import { LedgerExplorer } from "@/components/ledger/LedgerExplorer";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./ledger-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Household ledger",
};

export default function LedgerPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Household ledger</h1>
        <p className={styles.subheading}>
          Every recurring commitment and ledger event currently in the household graph, the running
          recovered-money counter, open disputes presented without a favoured side, and the last two payroll
          cycles with the register image shown beside the computed figure (PHASES.md Phase 7, spec §10, the
          Household Ledger). Cancelling a live mandate below routes through the same Approval Gate every
          payment action does.
        </p>
      </div>
      <LedgerExplorer baseUrl={getApiBaseUrl()} />
    </div>
  );
}
