import type { Metadata } from "next";
import { ConnectionsExplorer } from "@/components/connections/ConnectionsExplorer";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./connections-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Connections",
};

export default function ConnectionsPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Connections</h1>
        <p className={styles.subheading}>
          Connect Gmail or Outlook and GharOS reads the last 24 hours of mail through the official APIs, turning
          each real message into a real source document in the household graph (PHASES.md Phase 14.5). You can
          also drop in a receipt or a PDF, or pick a file from Drive. Every run reports exactly what it did,
          per document: what was added, what was already seen, what could not be read, and what it declined to
          guess at.
        </p>
      </div>
      <ConnectionsExplorer baseUrl={getApiBaseUrl()} />
    </div>
  );
}
