import type { Metadata } from "next";
import { ConciergeExplorer } from "@/components/concierge/ConciergeExplorer";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./concierge-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Outbound Concierge",
};

export default function ConciergePage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Outbound Concierge</h1>
        <p className={styles.subheading}>
          The system acts in the outside world, clarifying only what the graph can&apos;t already answer,
          ranking providers with reasons attached, calling on the household&apos;s behalf only once approved, and
          recording a booking only once it is independently verified. Every call below is a real, live,
          sandboxed text conversation, never synthesized audio.
        </p>
      </div>
      <ConciergeExplorer baseUrl={getApiBaseUrl()} />
    </div>
  );
}
