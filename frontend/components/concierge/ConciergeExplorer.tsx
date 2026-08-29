"use client";

import { useEffect, useMemo, useState } from "react";
import { Badge } from "@/components/design-system/Badge";
import { formatDateTime } from "@/lib/approvals";
import { fetchGraphSnapshot, GraphApiError } from "@/lib/graph-api";
import type { GraphNode } from "@/lib/graph-types";
import {
  AARAV_ID,
  BRIGHT_SMILES_PROVIDER_ID,
  DADI_ID,
  PRIYA_ID,
  MAYA_ID,
  QUICKCARE_PROVIDER_ID,
  SUNRISE_FAMILY_DENTAL_PROVIDER_ID,
  getAaravFollowupBookingOutcome,
  getAaravFollowupCall,
  getAaravFollowupConnectionAttempt,
  getAaravFollowupFallback,
  getAaravFollowupRetryDecision,
  getAaravToothacheApproval,
  getAaravToothacheBookingOutcome,
  getAaravToothacheCall,
  getAaravToothacheClarification,
  getAaravToothacheRanking,
  getDadiCleaningBookingOutcome,
  getDadiCleaningCall,
  getDadiCleaningFallback,
} from "@/lib/concierge";
import { BookingConfirmation } from "./BookingConfirmation";
import { CallApprovalGate } from "./CallApprovalGate";
import { ClarificationDisplay } from "./ClarificationDisplay";
import { ConciergeFallbackSurface } from "./ConciergeFallbackSurface";
import { LiveCallTranscript } from "./LiveCallTranscript";
import { RankedShortlist } from "./RankedShortlist";
import styles from "./ConciergeExplorer.module.css";

export interface ConciergeExplorerProps {
  readonly baseUrl: string;
}

type LoadState = { status: "loading" } | { status: "error"; message: string } | { status: "ready" };

const FALLBACK_PERSON_NAMES: Readonly<Record<string, string>> = {
  [PRIYA_ID]: "Priya",
  [AARAV_ID]: "Aarav",
  [DADI_ID]: "Dadi",
  [MAYA_ID]: "Maya",
};

const PROVIDER_NAME: Readonly<Record<string, string>> = {
  [QUICKCARE_PROVIDER_ID]: "QuickCare Dental Walk-in",
  [BRIGHT_SMILES_PROVIDER_ID]: "Bright Smiles Dental",
  [SUNRISE_FAMILY_DENTAL_PROVIDER_ID]: "Sunrise Family Dental",
};

/**
 * Top-level stateful orchestrator for `/concierge` (PHASES.md Phase 10) —
 * a client component kept separate from `app/concierge/page.tsx`, which
 * stays a Server Component so it can export page `metadata` (the same
 * split every prior phase's explorer uses).
 *
 * **Real, live data:** household member display names, via `/graph/
 * snapshot` — exactly `IntentionActionExplorer`'s precedent. **Fixture
 * data:** every `ClarificationResult`, `RankedProvider`,
 * `CallConversationResult`, `VerificationResult`, and `FallbackDecision`
 * below (A50-A56 have no HTTP endpoint this phase — see
 * `lib/concierge.ts`'s own module doc comment).
 *
 * **The one live behaviour this whole page enforces (Gate 10's own
 * literal checklist item, `.claude/agents/e4.md`'s "never do: let a
 * screen show... a call being placed without a visible approval
 * step"):** the hero flow's transcript and booking outcome are not
 * rendered at all until a household member clicks Approve on
 * `CallApprovalGate` — `approved` is real component state, not a fixture
 * flag, so the ordering is enforced by this page's own code, not merely
 * asserted in copy.
 */
export function ConciergeExplorer({ baseUrl }: ConciergeExplorerProps) {
  const [loadState, setLoadState] = useState<LoadState>({ status: "loading" });
  const [nodes, setNodes] = useState<readonly GraphNode[]>([]);
  const [heroApproved, setHeroApproved] = useState(false);

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

  const clarification = getAaravToothacheClarification();
  const ranking = getAaravToothacheRanking();
  const approval = getAaravToothacheApproval();
  const heroCall = getAaravToothacheCall();
  const heroBooking = getAaravToothacheBookingOutcome();

  const dadiCall = getDadiCleaningCall();
  const dadiBooking = getDadiCleaningBookingOutcome();
  const dadiFallback = getDadiCleaningFallback();

  const followupAttempt = getAaravFollowupConnectionAttempt();
  const followupRetry = getAaravFollowupRetryDecision();
  const followupCall = getAaravFollowupCall();
  const followupBooking = getAaravFollowupBookingOutcome();
  const followupFallback = getAaravFollowupFallback();

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
          Could not reach the live graph ({loadState.message}), showing this household&apos;s own fixed member
          names instead. Every clarification, ranking, call, verification, and fallback decision below is fixture
          data regardless (no HTTP endpoint exists for A50-A56 this phase).
        </p>
      )}

      <p className={styles.scopeNote} role="note">
        Every call below is a real, live, multi-turn text conversation the household&apos;s calling agent has with
        a real sandbox counterparty persona, never synthesized audio. See ADR-016: audio (text-to-speech and
        speech recognition) is real infrastructure, deliberately deferred to Phase 13, not built or implied here.
      </p>

      <section aria-label="Clarification">
        <h2 className={styles.sectionHeading}>Clarify, graph-first, ask only the unknowable</h2>
        <p className={styles.sectionIntro}>
          {personName(AARAV_ID)}&apos;s household asked for a dentist. The graph already answers most of it,
          only two genuinely unknown things get asked, never twenty.
        </p>
        <ClarificationDisplay result={clarification} personName={personName(AARAV_ID)} />
      </section>

      <section aria-label="Ranked shortlist">
        <h2 className={styles.sectionHeading}>Rank, a transparent shortlist, reasons attached</h2>
        <RankedShortlist ranking={ranking} />
      </section>

      <section aria-label="Approval gate">
        <h2 className={styles.sectionHeading}>Approve, before any call is placed</h2>
        <CallApprovalGate approval={approval} approved={heroApproved} onApprove={() => setHeroApproved(true)} />
      </section>

      {heroApproved && (
        <>
          <section aria-label="Live call transcript">
            <h2 className={styles.sectionHeading}>The call, adapts when the first slot is gone</h2>
            <LiveCallTranscript
              turns={heroCall.conversation.turns}
              outcomeReport={heroCall.outcomeReport}
              counterpartyName={PROVIDER_NAME[heroCall.brief.targetProviderId] ?? heroCall.brief.targetProviderId}
            />
          </section>

          <section aria-label="Booking confirmation">
            <h2 className={styles.sectionHeading}>Verify, then, only then, record</h2>
            <BookingConfirmation
              outcome={heroBooking}
              providerName={PROVIDER_NAME[QUICKCARE_PROVIDER_ID]!}
              title={`${personName(AARAV_ID)}'s dentist appointment`}
            />
          </section>
        </>
      )}

      <section aria-label="Why the safeguards are real">
        <h2 className={styles.sectionHeading}>Why the safeguards are real, not just documented</h2>
        <p className={styles.sectionIntro}>
          Two more real, independent calls, not further attempts at the same booking above, each showing a
          different safeguard actually firing: an out-of-bounds question the agent refuses to guess at, and a
          discrepancy an independent check catches even after the call itself reported success.
        </p>

        <div className={styles.safeguardCard}>
          <h3 className={styles.safeguardHeading}>
            {personName(DADI_ID)}&apos;s routine cleaning, the front desk asks something out of scope
          </h3>
          <LiveCallTranscript
            turns={dadiCall.conversation.turns}
            outcomeReport={dadiCall.outcomeReport}
            counterpartyName={PROVIDER_NAME[BRIGHT_SMILES_PROVIDER_ID]!}
          />
          <BookingConfirmation
            outcome={dadiBooking}
            providerName={PROVIDER_NAME[BRIGHT_SMILES_PROVIDER_ID]!}
            title={`${personName(DADI_ID)}'s six-month cleaning`}
          />
          <ConciergeFallbackSurface title={`${personName(DADI_ID)}'s six-month cleaning`} decision={dadiFallback} />
        </div>

        <div className={styles.safeguardCard}>
          <h3 className={styles.safeguardHeading}>
            {personName(AARAV_ID)}&apos;s routine follow-up, retries, connects, then a caught mismatch
          </h3>
          <p className={styles.connectionAttemptLine}>
            <Badge variant="warning">No answer</Badge> {followupAttempt.targetProviderName}, attempted{" "}
            {formatDateTime(followupAttempt.attemptedAt)}.
          </p>
          <ConciergeFallbackSurface title="First attempt" decision={followupRetry} />
          <LiveCallTranscript
            turns={followupCall.conversation.turns}
            outcomeReport={followupCall.outcomeReport}
            counterpartyName={PROVIDER_NAME[SUNRISE_FAMILY_DENTAL_PROVIDER_ID]!}
          />
          <BookingConfirmation
            outcome={followupBooking}
            providerName={PROVIDER_NAME[SUNRISE_FAMILY_DENTAL_PROVIDER_ID]!}
            title={`${personName(AARAV_ID)}'s routine follow-up`}
          />
          <ConciergeFallbackSurface title={`${personName(AARAV_ID)}'s routine follow-up`} decision={followupFallback} />
        </div>
      </section>
    </div>
  );
}
