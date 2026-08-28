import type { Metadata } from "next";
import { SimulatorExplorer } from "@/components/simulator/SimulatorExplorer";
import styles from "./simulator-page.module.css";

export const metadata: Metadata = {
  title: "GharOS — Household Simulator",
};

export default function SimulatorPage() {
  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Household Simulator</h1>
        <p className={styles.subheading}>
          Branch comparison for the household&apos;s live decisions — every projected impact traceable to
          household graph data or a cited external source with a retrieval timestamp, a risk register drawn
          from the critic&apos;s own pushback, this household&apos;s calibrated variance on past decisions in
          the same category, and an interrogation mode for follow-up questions. Trade-offs are presented for
          the household to weigh — never a verdict on an emotionally-loaded family decision (PHASES.md Phase
          11, spec §11.4, §11.6).
        </p>
      </div>
      <SimulatorExplorer />
    </div>
  );
}
