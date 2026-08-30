import type { Metadata } from "next";
import { CouncilExplorer } from "@/components/council/CouncilExplorer";
import { CouncilHistoryBrowser } from "@/components/council/CouncilHistoryBrowser";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./council-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Household Council",
};

export default function CouncilPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Household Council</h1>
        <p className={styles.subheading}>
          Major household decisions convene specialists who each query a genuinely different subgraph, member
          delegates who each carry a real conflicting interest, and an Adversary structurally tasked with
          attacking the leading option. A deterministic mechanism, never an LLM, computes the explicit
          trade-off. The Council never makes the final call: it produces a brief, and the household decides.
        </p>
      </div>

      <CouncilExplorer />

      <section className={styles.historySection} aria-label="Historical decision browser">
        <h2 className={styles.historyHeading}>Why did we decide this?</h2>
        <p className={styles.historyIntro}>
          Every past council decision, permanently recorded, its trigger, every branch it weighed, every
          position that named it, and who is recorded as having conceded. Institutional memory a family can
          actually consult two years later.
        </p>
        <CouncilHistoryBrowser baseUrl={getApiBaseUrl()} />
      </section>
    </div>
  );
}
