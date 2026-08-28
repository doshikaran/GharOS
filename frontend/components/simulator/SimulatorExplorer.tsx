"use client";

import { useState } from "react";
import {
  buildRiskRegister,
  getBackwardModeAnalysis,
  getBranchCritiques,
  getBranchProjections,
  getCalibrationEstimate,
  getDecisionBrief,
  getDecisionFrame,
  getGroundingResults,
} from "@/lib/simulator";
import { BackwardModeView } from "./BackwardModeView";
import { BranchComparison } from "./BranchComparison";
import { CalibrationPanel } from "./CalibrationPanel";
import { DecisionFramingHeader } from "./DecisionFramingHeader";
import { InterrogationPanel } from "./InterrogationPanel";
import { RiskRegister } from "./RiskRegister";
import styles from "./SimulatorExplorer.module.css";

type Mode = "forward" | "backward";

/** This decision's `Outcome.attribution_tags` category (ADR-017's
 * decision-category vocabulary) — the household's redevelopment/
 * relocation decision falls under `"relocation"`. Hardcoded here rather
 * than added to `DecisionFrame` because the six-agent contract given for
 * this phase does not carry a category field on that type; it belongs to
 * A39 Calibration's own lookup, which this page performs directly. */
const DECISION_CATEGORY_TAG = "relocation";

/**
 * Top-level stateful orchestrator for `/simulator` (PHASES.md Phase 11) —
 * a client component kept separate from `app/simulator/page.tsx`, which
 * stays a Server Component so it can export page `metadata` (same split
 * as every prior phase's explorer).
 *
 * Forward mode (branch comparison, risk register, calibration,
 * interrogation) and backward mode are rendered as two distinct,
 * clearly-labelled tabs (ADR-017 Decision 3: the same six agents, a
 * second entry point, never a seventh agent) — never blended into one
 * view.
 */
export function SimulatorExplorer() {
  const [mode, setMode] = useState<Mode>("forward");

  const decisionFrame = getDecisionFrame();
  const branchProjections = getBranchProjections();
  const groundingResults = getGroundingResults();
  const branchCritiques = getBranchCritiques();
  const decisionBrief = getDecisionBrief();
  const calibrationEstimate = getCalibrationEstimate(DECISION_CATEGORY_TAG);
  const backwardModeAnalysis = getBackwardModeAnalysis();
  const riskRegisterEntries = buildRiskRegister(branchCritiques, branchProjections);

  return (
    <div className={styles.explorer}>
      <DecisionFramingHeader frame={decisionFrame} />

      <div role="tablist" aria-label="Simulator mode" className={styles.tabList}>
        <button
          type="button"
          role="tab"
          id="simulator-tab-forward"
          aria-selected={mode === "forward"}
          aria-controls="simulator-panel-forward"
          className={`${styles.tab} ${mode === "forward" ? styles.tabActive : ""}`}
          onClick={() => setMode("forward")}
        >
          Forward — branch comparison
        </button>
        <button
          type="button"
          role="tab"
          id="simulator-tab-backward"
          aria-selected={mode === "backward"}
          aria-controls="simulator-panel-backward"
          className={`${styles.tab} ${mode === "backward" ? styles.tabActive : ""}`}
          onClick={() => setMode("backward")}
        >
          Backward mode
        </button>
      </div>

      {mode === "forward" && (
        <div
          role="tabpanel"
          id="simulator-panel-forward"
          aria-labelledby="simulator-tab-forward"
          className={styles.tabPanel}
        >
          <section className={styles.section} aria-label="Branch comparison">
            <h2 className={styles.sectionHeading}>Branch comparison</h2>
            <p className={styles.sectionIntro}>
              Every projected impact below is traceable to either household graph data or a cited external
              source with a retrieval timestamp — never an unsourced claim (Gate 11). The critic&apos;s pushback
              is shown separately from each branch&apos;s own projection, not blended into it.
            </p>
            <BranchComparison
              projections={branchProjections}
              groundingResults={groundingResults}
              critiques={branchCritiques}
            />
          </section>

          <section className={styles.section} aria-label="Risk register">
            <h2 className={styles.sectionHeading}>Risk register</h2>
            <p className={styles.sectionIntro}>
              Every over-optimistic claim and omitted second-order effect the critic raised, across every branch,
              flattened into one scannable list.
            </p>
            <RiskRegister entries={riskRegisterEntries} />
          </section>

          <section className={styles.section} aria-label="Calibration">
            <h2 className={styles.sectionHeading}>Calibration</h2>
            <p className={styles.sectionIntro}>
              This household&apos;s own variance for past decisions in the same category (
              <code>{DECISION_CATEGORY_TAG}</code>) — stated honestly, including when the history is too thin to
              support a confidence figure (spec §11.5).
            </p>
            <CalibrationPanel estimate={calibrationEstimate} />
          </section>

          <section className={styles.section} aria-label="Interrogation mode">
            <h2 className={styles.sectionHeading}>Interrogation mode</h2>
            <p className={styles.sectionIntro}>
              Ask a follow-up question about this decision. Trade-offs are presented for the household to weigh —
              never a verdict on an emotionally-loaded family decision.
            </p>
            <InterrogationPanel brief={decisionBrief} />
          </section>
        </div>
      )}

      {mode === "backward" && (
        <div
          role="tabpanel"
          id="simulator-panel-backward"
          aria-labelledby="simulator-tab-backward"
          className={styles.tabPanel}
        >
          <section className={styles.section} aria-label="Backward mode analysis">
            <h2 className={styles.sectionHeading}>Backward mode</h2>
            <p className={styles.sectionIntro}>
              Take a committed plan, assume it failed, and reason backwards using this household&apos;s own
              OUTCOME history to identify the likely failure point (ADR-017).
            </p>
            <BackwardModeView analysis={backwardModeAnalysis} />
          </section>
        </div>
      )}
    </div>
  );
}
