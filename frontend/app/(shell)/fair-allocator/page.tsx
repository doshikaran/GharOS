import type { Metadata } from "next";
import { FairAllocatorExplorer } from "@/components/fair-allocator/FairAllocatorExplorer";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./fair-allocator-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Fair Allocator",
};

export default function FairAllocatorPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Fair Allocator</h1>
        <p className={styles.subheading}>
          The household&apos;s real cost matrix, visible and confirmable, never hidden, a deterministic solve of
          this cycle&apos;s shared errands, its envy-free-up-to-one-item verification, per-person explanations
          grounded in each person&apos;s own stated costs, a live renegotiation triggered by a real household change,
          and a browsable load-imbalance check (PHASES.md Phase 8, spec §8, the Fair Allocator).
        </p>
      </div>
      <FairAllocatorExplorer baseUrl={getApiBaseUrl()} />
    </div>
  );
}
