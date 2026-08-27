"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { fetchGraphSnapshot, GraphApiError } from "@/lib/graph-api";
import type { GraphNode } from "@/lib/graph-types";
import type { ScheduleConstraintInput } from "@/lib/schedule-availability";
import {
  AARAV_ID,
  DADI_ID,
  DADI_NAP_CONSTRAINT_ID,
  DENTAL_CHECKUP_RESOLUTION_SECONDS,
  MAYA_ID,
  PRIYA_ID,
  applyDiagnosisCorrection,
  buildDadiPhysioWindowResult,
  getDadiPhysioDiagnosis,
  getDentalCheckupAttempts,
  getDentalCheckupCurrentDiagnosis,
  getDentalCheckupModalitySwitch,
  getDentalCheckupSlippageAnalysis,
  getDentalCheckupWindow,
  getEyeCheckupDiagnosis,
  getEyeCheckupInformationFetch,
  getFieldTripDecisionNarrowing,
  getFieldTripDiagnosis,
  getInitialFrictionPatterns,
  getStaleObligationDetection,
  type DiagnosisCorrection,
  type FrictionPattern,
} from "@/lib/intention-action";
import { BlockerTaxonomyLegend } from "./BlockerTaxonomyLegend";
import { DemoBeatTimeline } from "./DemoBeatTimeline";
import { DiagnosisCorrectionForm } from "./DiagnosisCorrectionForm";
import { DiagnosisDisplay } from "./DiagnosisDisplay";
import { FrictionProfileView } from "./FrictionProfileView";
import { SlippageEscalationSurface } from "./SlippageEscalationSurface";
import { UnblockOutcomeGallery } from "./UnblockOutcomeGallery";
import styles from "./IntentionActionExplorer.module.css";

export interface IntentionActionExplorerProps {
  readonly baseUrl: string;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

const FALLBACK_PERSON_NAMES: Readonly<Record<string, string>> = {
  [PRIYA_ID]: "Priya",
  [AARAV_ID]: "Aarav",
  [DADI_ID]: "Dadi",
  [MAYA_ID]: "Maya",
};

/**
 * Top-level stateful orchestrator for `/intention-action` (PHASES.md Phase
 * 9) — a client component kept separate from `app/intention-action/
 * page.tsx`, which stays a Server Component so it can export page
 * `metadata` (the same split every prior phase's explorer uses).
 *
 * **Real, live data**: household member display names, and Dadi's real,
 * live `constraint-dadi-nap` (`/graph/snapshot`) — used directly to
 * compute the window-blocker demo's person-availability verdicts. **Fixture
 * data**: every `BlockerDiagnosis`, unblock result, and slippage analysis
 * (A23-A26 have no HTTP endpoint this phase — see `lib/intention-action.ts`'s
 * own module doc comment).
 *
 * **The one live behaviour this whole page exists to prove (Gate 9's own
 * literal checklist item)**: submitting a correction in
 * `DiagnosisCorrectionForm` calls `applyDiagnosisCorrection` and replaces
 * `frictionPatterns` state — `FrictionProfileView` re-renders from that
 * same state in the same pass, so the correction's effect on the friction
 * profile is observable in this one session, not a separate demo.
 */
export function IntentionActionExplorer({ baseUrl }: IntentionActionExplorerProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [nodes, setNodes] = useState<readonly GraphNode[]>([]);
  const [frictionPatterns, setFrictionPatterns] = useState<readonly FrictionPattern[]>(getInitialFrictionPatterns());
  const [submittedCorrection, setSubmittedCorrection] = useState<DiagnosisCorrection | null>(null);
  const [justUpdatedPatternId, setJustUpdatedPatternId] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchGraphSnapshot(baseUrl)
      .then((snapshot) => {
        if (cancelled) return;
        setNodes(snapshot.nodes);
        setLoadState({ status: "ready" });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // A failed live fetch degrades to the real household's own fixed
        // display names (`FALLBACK_PERSON_NAMES`) rather than blocking this
        // page — every diagnosis/outcome/escalation below is fixture data
        // anyway; only the person names and Dadi's live schedule constraint
        // were ever going to come from this fetch.
        const message = err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load live graph data.";
        setLoadState({ status: "error", message });
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  const personName = useMemo(() => {
    const fromLive = new Map(
      nodes.filter((node) => node.type === "PERSON").map((node) => [node.id, String(node.fields.display_name ?? node.label)]),
    );
    return (personId: string) => fromLive.get(personId) ?? FALLBACK_PERSON_NAMES[personId] ?? personId;
  }, [nodes]);

  const people = useMemo(
    () => [PRIYA_ID, AARAV_ID, DADI_ID, MAYA_ID].map((personId) => ({ personId, displayName: personName(personId) })),
    [personName],
  );

  const realDadiNapConstraint = useMemo<ScheduleConstraintInput | null>(() => {
    const node = nodes.find((n) => n.type === "CONSTRAINT" && n.id === DADI_NAP_CONSTRAINT_ID);
    if (!node) return null;
    const kind = String(node.fields.kind ?? "");
    const severity = String(node.fields.severity ?? "");
    const structured = (node.fields.structured ?? {}) as Record<string, string>;
    if (kind !== "schedule" || (severity !== "hard" && severity !== "soft")) return null;
    return { id: node.id, kind: "schedule", severity, structured };
  }, [nodes]);

  const eyeCheckupDiagnosis = getEyeCheckupDiagnosis();
  const dentalCurrentDiagnosis = getDentalCheckupCurrentDiagnosis();
  const dentalAttempts = getDentalCheckupAttempts();
  const windowResult = useMemo(() => buildDadiPhysioWindowResult(realDadiNapConstraint), [realDadiNapConstraint]);

  function handleCorrectionSubmit(correction: DiagnosisCorrection) {
    const result = applyDiagnosisCorrection(frictionPatterns, correction, personName(correction.personId));
    setFrictionPatterns(result.patterns);
    setJustUpdatedPatternId(result.writtenPattern.id);
    setSubmittedCorrection(correction);
  }

  if (loadState.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading the household&apos;s current graph…
      </p>
    );
  }

  return (
    <div className={styles.explorer}>
      {loadState.status === "error" && (
        <p className={styles.statusWarning} role="alert">
          Could not reach the live graph ({loadState.message}) — showing this household&apos;s own fixed member
          names instead. Every diagnosis, unblock outcome, and escalation below is fixture data regardless (no HTTP
          endpoint exists for A23-A26 this phase).
        </p>
      )}

      <section aria-label="The six-type taxonomy">
        <h2 className={styles.sectionHeading}>The six-type blocker taxonomy</h2>
        <p className={styles.sectionIntro}>
          spec §9.3&apos;s core reasoning step — the specific obstacle keeping an intention from becoming action is
          always exactly one of these six, never a vague &ldquo;it&apos;s complicated.&rdquo;
        </p>
        <BlockerTaxonomyLegend />
      </section>

      <section aria-label="Stale obligation detected">
        <h2 className={styles.sectionHeading}>Stale obligation, detected unprompted</h2>
        <Card className={styles.staleCard}>
          <div className={styles.staleRow}>
            <Badge variant="danger">{getStaleObligationDetection().daysStale} days stale</Badge>
            <strong>{getStaleObligationDetection().title}</strong>
          </div>
          <p className={styles.staleReason}>{getStaleObligationDetection().reason}</p>
        </Card>
      </section>

      <section aria-label="Diagnosis with a real correction affordance">
        <h2 className={styles.sectionHeading}>Diagnosis — and a real correction affordance</h2>
        <p className={styles.sectionIntro}>
          Dadi&apos;s eye check-up: diagnosed as an information blocker, and genuinely unblocked as one below. Read
          it, then correct it if you disagree — the correction updates {personName(eyeCheckupDiagnosis.personId)}
          &apos;s friction profile directly beneath it, in this same session.
        </p>
        <div className={styles.diagnosisAndCorrection}>
          <DiagnosisDisplay
            diagnosis={eyeCheckupDiagnosis}
            obligationTitle="Book Dadi's follow-up eye check-up"
            personName={personName(eyeCheckupDiagnosis.personId)}
          />
          <DiagnosisCorrectionForm
            diagnosis={eyeCheckupDiagnosis}
            people={people}
            onSubmit={handleCorrectionSubmit}
            submittedCorrection={submittedCorrection}
          />
        </div>
      </section>

      <section aria-label="Friction profile">
        <h2 className={styles.sectionHeading}>Friction profile, per person</h2>
        <p className={styles.sectionIntro}>
          Every real, accumulated blocker pattern on file for each household member — support count grows with real
          evidence, never asserted as certainty from one data point.
        </p>
        <FrictionProfileView patterns={frictionPatterns} people={people} justUpdatedPatternId={justUpdatedPatternId} />
      </section>

      <section aria-label="Unblock outcomes">
        <h2 className={styles.sectionHeading}>What actually happened — the four unblock outcomes</h2>
        <UnblockOutcomeGallery
          informationOutcome={getEyeCheckupInformationFetch()}
          decisionOutcome={getFieldTripDecisionNarrowing()}
          aversionOutcome={getDentalCheckupModalitySwitch()}
          windowOutcome={windowResult}
          windowPersonName={personName(getDadiPhysioDiagnosis().personId)}
        />
      </section>

      <section aria-label="Decision blocker diagnosis">
        <h2 className={styles.sectionHeading}>Decision blocker, diagnosed</h2>
        <DiagnosisDisplay
          diagnosis={getFieldTripDiagnosis()}
          obligationTitle="Choose how to pay for Aarav's school field trip"
          personName={personName(getFieldTripDiagnosis().personId)}
        />
      </section>

      <section aria-label="Window blocker diagnosis">
        <h2 className={styles.sectionHeading}>Window blocker, diagnosed</h2>
        <DiagnosisDisplay
          diagnosis={getDadiPhysioDiagnosis()}
          obligationTitle="Escort Dadi to her physiotherapy session"
          personName={personName(getDadiPhysioDiagnosis().personId)}
        />
      </section>

      <section aria-label="Re-diagnosis and slippage escalation">
        <h2 className={styles.sectionHeading}>Aarav&apos;s dental check-up — re-diagnosed, then escalated</h2>
        <DiagnosisDisplay
          diagnosis={dentalCurrentDiagnosis}
          obligationTitle="Book Aarav's dental check-up"
          personName={personName(dentalCurrentDiagnosis.personId)}
        />
        <SlippageEscalationSurface
          obligationTitle="Book Aarav's dental check-up"
          attempts={dentalAttempts}
          analysis={getDentalCheckupSlippageAnalysis()}
          delegateName={personName}
        />
      </section>

      <section aria-label="The demo beat">
        <h2 className={styles.sectionHeading}>Untouched for months, now moving</h2>
        <p className={styles.sectionIntro}>
          Instead of acting on any of the three escalation options above, correctly targeting the real blocker
          (aversion, not information) resolved this before a human needed to choose.
        </p>
        <DemoBeatTimeline
          stale={getStaleObligationDetection()}
          attemptCount={dentalAttempts.length}
          modalitySwitch={getDentalCheckupModalitySwitch()}
          windowResult={getDentalCheckupWindow()}
          resolutionSeconds={DENTAL_CHECKUP_RESOLUTION_SECONDS}
        />
      </section>
    </div>
  );
}
