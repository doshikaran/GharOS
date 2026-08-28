import type { Metadata } from "next";
import { StatusBoard } from "@/components/status/StatusBoard";
import styles from "./status-page.module.css";

export const metadata: Metadata = {
  title: "GharOS — Stack status",
};

export default function StatusPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Stack status</h1>
        <p className={styles.subheading}>
          Proves the deployed frontend can reach the deployed <code>gharos-api</code> backend
          (PHASES.md Phase 2, Gate 2) — each card below calls a real endpoint on load and shows
          the real response, or the real error if one occurred.
        </p>
      </div>
      <StatusBoard />
    </div>
  );
}
