/**
 * TypeScript mirrors of the Phase 10 Outbound Concierge's real agent
 * output shapes (PHASES.md Phase 10, E4 work item — "ranked shortlist
 * with reasons; live call status; booking confirmation"), plus a real
 * port of the two structural guarantees Gate 10 is actually graded on.
 *
 * Source of truth, read directly rather than guessed at:
 *   - `backend/app/agents/concierge/types.py` — every shape below
 *     (`GraphKnownFact`, `ClarifyingQuestion`, `ClarificationResult`,
 *     `ProviderCandidate`, `RankedProvider`, `ProviderRankingResult`,
 *     `CallBrief`, `CallTurn`, `CallConversationResult`,
 *     `CallOutcomeReport`, `VerificationVerdict`, `VerificationResult`,
 *     `VerifiedBooking`, `FallbackAction`, `FallbackDecision`,
 *     `FallbackEscalationPayload`) is a field-for-field mirror of that
 *     module's real, frozen dataclasses.
 *   - `backend/app/agents/concierge/verification.py` — `verify_call_
 *     outcome`'s real, deterministic cross-check logic, which this file's
 *     `verifyCallOutcome` ports line for line (see that function's own
 *     doc comment).
 *   - `backend/app/tools/booking_write_tool.py` — `verified_booking_
 *     from_verification`'s real "no write without verification" guard,
 *     ported below as `buildBookingOutcome`.
 *   - `contracts/actions.py` — `EvidenceBundle`/`RiskTier`, reused
 *     directly from `lib/approvals.ts` rather than re-mirrored here (this
 *     file's `FallbackEscalationPayload.evidenceBundle`/`.riskTier` are
 *     the exact same shape spec §18.2 already defined for the Approval
 *     Gate — no reason to duplicate it).
 *   - `docs/adr/016-outbound-concierge-scope.md` — binding for every
 *     piece of copy in this file and the components that render it: the
 *     call is a real, live, multi-turn TEXT conversation against a real
 *     sandbox counterparty persona, never synthesized audio. Nothing in
 *     this file or its consumers may imply a phone literally rang.
 *
 * Field names are camelCase, following `lib/fair-allocator.ts`'s
 * established fixture/wire-seam convention — every field maps 1:1 to its
 * snake_case Python name.
 *
 * **DATA-LOADING BOUNDARY (this phase's own brief, this file's documented
 * seam).** None of A50-A56's output shapes have a REST endpoint this
 * phase — no role built one; Phase 10's backend work was agents + tools,
 * not a new API surface (matching the precedent every phase since 5 has
 * set: `lib/fair-allocator.ts`, `lib/intention-action.ts`). Every
 * `get*()` function below is a fixture-backed seam: realistic,
 * richly-varied data typed exactly as the real backend shape, so every
 * consumer component depends only on the return type, never the fixture
 * body. `components/concierge/ConciergeExplorer.tsx` separately fetches
 * the live `/graph/snapshot` for real household member display names,
 * exactly like `IntentionActionExplorer` — that is the only live data
 * this subsystem's UI touches.
 *
 * Continuous with `backend/seeds/demo_household.py` and every prior
 * phase's fixtures — the same household (Priya, Aarav, Dadi, Maya), never
 * a second, disconnected demo family. Three independent, real scenarios
 * are told below, deliberately not three attempts at the same booking
 * (mirrors `lib/intention-action.ts`'s `UnblockOutcomeGallery` precedent
 * of showing distinct real outcomes side by side rather than forcing one
 * obligation through every branch):
 *
 *   A. **Aarav, a sore tooth since Tuesday** — the hero flow. Urgent
 *      (pain reported), a real ranked shortlist, a call that adapts when
 *      its first-choice slot is gone, a real verified booking. This is
 *      Gate 10's "book a dentist" demo beat end to end.
 *   B. **Dadi, a routine six-month cleaning** — the front desk asks for
 *      her date of birth, which was never pre-authorised to share; the
 *      agent takes a message instead of guessing (spec §13.6) rather than
 *      completing the call. Nothing is recorded.
 *   C. **Aarav, a routine follow-up** — a real retry after no answer,
 *      then a call that *itself* reports success, but an independent
 *      structural check (A55) catches that the offered slot doesn't
 *      match either of the two windows the household actually authorised
 *      — the precise reason A55 exists as a separate, non-bypassable
 *      step rather than trusting A54's own in-call bounds check alone.
 *
 * `provider-bright-smiles-dental`'s last-visit fact (12 Feb 2026) is the
 * same real fact `lib/intention-action.ts` established for this
 * household's dental history — reused verbatim, not re-invented.
 */

import type { EvidenceBundle, RiskTier } from "./approvals";

// ---------------------------------------------------------------------------
// Real node ids this fixture data is built on top of (gharos-standards: no
// magic values re-typed at each call site) — matches
// `backend/seeds/demo_household.py` / `lib/intention-action.ts` exactly.
// ---------------------------------------------------------------------------

export const PRIYA_ID = "person-priya";
export const AARAV_ID = "person-aarav";
export const DADI_ID = "person-dadi";
export const MAYA_ID = "person-maya";

/** Reference instant this fixture set is built around — a Friday
 * afternoon, matching the household's real current point in the project
 * timeline. Scenario C's retry/callback fixtures fall the following
 * week, on their own explicit dates. */
export const CONCIERGE_NOW = "2026-08-28T15:30:00Z";

/** Mirrors `requirement_clarifier_agent.MAX_CLARIFYING_QUESTIONS` — Gate
 * 10's own literal ceiling ("'Book a dentist' asks <=2 questions"). */
export const MAX_CLARIFYING_QUESTIONS = 2;

// ---------------------------------------------------------------------------
// A50 Requirement Clarifier — `types.py`'s `UrgencyLevel`, `GraphKnownFact`,
// `ClarifyingQuestion`, `ClarificationResult`
// ---------------------------------------------------------------------------

export type UrgencyLevel = "routine" | "elevated";

export interface GraphKnownFact {
  readonly field: string;
  readonly value: string;
  readonly source: string;
}

export interface ClarifyingQuestion {
  readonly text: string;
  readonly targetsUnknown: string;
  readonly decisionRelevance: string;
}

export interface ClarificationResult {
  readonly personId: string;
  readonly serviceCategory: string;
  readonly householdRequestText: string;
  readonly resolvedFromGraph: readonly GraphKnownFact[];
  readonly questions: readonly ClarifyingQuestion[];
  readonly assumptions: readonly string[];
  readonly urgency: UrgencyLevel;
  readonly urgencyReasoning: string;
  readonly confidence: number;
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
  readonly clarifiedAt: string;
}

/**
 * Scenario A's clarification pass. Three genuine graph-unresolvable
 * unknowns were candidates (`pain_severity`, `date_constraints`,
 * `clinic_preference`) — only the top two became real questions
 * (`MAX_CLARIFYING_QUESTIONS`); the third became a stated assumption
 * instead of being silently dropped, so the ceiling is demonstrably real
 * rather than merely documented.
 */
export function getAaravToothacheClarification(): ClarificationResult {
  return {
    personId: AARAV_ID,
    serviceCategory: "dentist",
    householdRequestText:
      "Priya: Aarav's tooth has been hurting since Tuesday, can someone get him in to see a dentist?",
    resolvedFromGraph: [
      {
        field: "last_visit_date",
        value: "2026-02-12",
        source: "neighbours(person-aarav, BOOKED_WITH) → provider-bright-smiles-dental, last completed visit",
      },
      {
        field: "insurance_coverage",
        value: "Apollo Health Shield family floater, dental rider active",
        source: "PERSON → HAS_INSURANCE edge, person-aarav",
      },
      {
        field: "availability_model",
        value: "School 8:30am–3:30pm weekdays; free from 4:30pm onward weekdays and all day Saturday",
        source: "SCHEDULE constraint, person-aarav",
      },
      {
        field: "prior_provider_history",
        value: "Bright Smiles Dental, 2 routine visits on file, no complaints",
        source: "booked_with history → completes_into Outcome, provider-bright-smiles-dental",
      },
    ],
    questions: [
      {
        text: "How bad is the pain right now, enough that it should be seen today, or can it wait a day or two?",
        targetsUnknown: "pain_severity",
        decisionRelevance:
          "Directly sets urgency: elevated urgency prioritises the earliest available slot over rating (spec §13.2 Step 1).",
      },
      {
        text: "Is there any day this week Aarav can't do at all, a test, a match, anything fixed?",
        targetsUnknown: "date_constraints",
        decisionRelevance:
          "Narrows the authorised date range handed to the Call Planner so the call never proposes a time that's actually unworkable.",
      },
    ],
    assumptions: [
      "No stated clinic preference, ranking below considers Bright Smiles Dental alongside nearby alternatives rather than assuming continuity is required, since a same-day slot may matter more than loyalty right now.",
    ],
    urgency: "elevated",
    urgencyReasoning:
      "The household's own request states the tooth has been hurting since Tuesday (three days), spec §13.2 Step 1's \"if pain is reported → urgency escalates\" applies directly from the request text itself, before either clarifying question above is even answered.",
    confidence: 0.86,
    modelTier: "pro",
    promptVersion: "requirement-clarifier-v1",
    invocationId: "inv-a50-aarav-toothache-1",
    clarifiedAt: "2026-08-28T15:31:00Z",
  };
}

// ---------------------------------------------------------------------------
// A51/A52 — `ProviderCandidate`, `ProviderReliabilitySignal`,
// `RankedProvider`, `ProviderRankingResult`
// ---------------------------------------------------------------------------

export interface ProviderCandidate {
  readonly providerId: string;
  readonly name: string;
  readonly category: string;
  readonly rating: number | null;
  readonly distanceKm: number | null;
  readonly availabilityNotes: string | null;
  readonly priceBand: string | null;
  readonly specialisations: readonly string[];
  readonly isExistingHouseholdProvider: boolean;
}

export interface ProviderReliabilitySignal {
  readonly providerId: string;
  readonly noShowCount: number;
  readonly onTimeCount: number;
  readonly rescheduledCount: number;
  readonly unresponsiveCount: number;
  readonly totalOutcomesConsidered: number;
}

export interface RankedProvider {
  readonly providerId: string;
  readonly name: string;
  /** 1-based; `1` is the top recommendation. */
  readonly rank: number;
  readonly score: number;
  readonly reasons: readonly string[];
  readonly demotedForReliability: boolean;
  readonly scoreComponents: Readonly<Record<string, number>>;
}

export interface ProviderRankingResult {
  readonly serviceCategory: string;
  readonly personId: string;
  readonly ranked: readonly RankedProvider[];
  readonly urgency: UrgencyLevel;
  readonly narrative: string;
  readonly confidence: number;
  readonly modelTier: "pro" | "deterministic";
  readonly promptVersion: string;
  readonly invocationId: string;
  readonly rankedAt: string;
}

export const QUICKCARE_PROVIDER_ID = "provider-quickcare-dental";
export const BRIGHT_SMILES_PROVIDER_ID = "provider-bright-smiles-dental";
export const SMILE_CARE_JUNCTION_PROVIDER_ID = "provider-smilecare-junction";
export const SUNRISE_FAMILY_DENTAL_PROVIDER_ID = "provider-sunrise-family-dental";

export function getAaravToothacheCandidates(): readonly ProviderCandidate[] {
  return [
    {
      providerId: QUICKCARE_PROVIDER_ID,
      name: "QuickCare Dental Walk-in",
      category: "dentist",
      rating: 4.5,
      distanceKm: 0.8,
      availabilityNotes: "Same-day slots most weekdays after 4pm; walk-ins welcome",
      priceBand: "₹₹",
      specialisations: ["general dentistry", "emergency walk-in"],
      isExistingHouseholdProvider: false,
    },
    {
      providerId: BRIGHT_SMILES_PROVIDER_ID,
      name: "Bright Smiles Dental",
      category: "dentist",
      rating: 4.7,
      distanceKm: 1.2,
      availabilityNotes: "Booked 3-4 days out for non-emergency slots",
      priceBand: "₹₹",
      specialisations: ["general dentistry", "pediatric dentistry", "geriatric care"],
      isExistingHouseholdProvider: true,
    },
    {
      providerId: SMILE_CARE_JUNCTION_PROVIDER_ID,
      name: "Smile Care Junction",
      category: "dentist",
      rating: 4.2,
      distanceKm: 2.4,
      availabilityNotes: "Slot open tomorrow morning",
      priceBand: "₹",
      specialisations: ["general dentistry"],
      isExistingHouseholdProvider: true,
    },
  ];
}

/** Real prior-experience signals for the two existing household
 * providers among `getAaravToothacheCandidates()` — QuickCare is new, so
 * it deliberately has none (a neutral, not-penalised, score component). */
export function getAaravToothacheReliabilitySignals(): readonly ProviderReliabilitySignal[] {
  return [
    {
      providerId: BRIGHT_SMILES_PROVIDER_ID,
      noShowCount: 0,
      onTimeCount: 2,
      rescheduledCount: 0,
      unresponsiveCount: 0,
      totalOutcomesConsidered: 2,
    },
    {
      providerId: SMILE_CARE_JUNCTION_PROVIDER_ID,
      noShowCount: 1,
      onTimeCount: 1,
      rescheduledCount: 0,
      unresponsiveCount: 0,
      totalOutcomesConsidered: 2,
    },
  ];
}

/**
 * Scenario A's real, explainable ranking — Gate 10's "the user sees why
 * #1 is #1," made literal: #1 (QuickCare) wins on same-day availability
 * under elevated urgency, specifically *despite* a lower rating than #2
 * (Bright Smiles) — the two providers' `reasons` are never
 * interchangeable. #3 (Smile Care Junction) is demoted for a real,
 * on-file no-show, visibly, not just sorted quietly to the bottom.
 */
export function getAaravToothacheRanking(): ProviderRankingResult {
  return {
    serviceCategory: "dentist",
    personId: AARAV_ID,
    urgency: "elevated",
    ranked: [
      {
        providerId: QUICKCARE_PROVIDER_ID,
        name: "QuickCare Dental Walk-in",
        rank: 1,
        score: 0.88,
        reasons: [
          "Earliest available slot, today after 4:30pm, which matters because Aarav's reported pain sets this to elevated urgency (spec §13.2 Step 1)",
          "0.8 km from home, the closest of the three options",
          "Rated 4.5/5",
          "Accepts Apollo Health Shield's dental rider",
        ],
        demotedForReliability: false,
        scoreComponents: { rating: 0.82, distance: 0.95, availability: 1.0, price: 0.65, reliability: 0.5 },
      },
      {
        providerId: BRIGHT_SMILES_PROVIDER_ID,
        name: "Bright Smiles Dental",
        rank: 2,
        score: 0.71,
        reasons: [
          "Highest rating of the three (4.7/5) and Aarav's own regular clinic, 2 prior visits on file, no complaints",
          "1.2 km from home",
          "Earliest slot is 3-4 days out, under elevated urgency that's slower than #1, which is exactly why a lower-rated same-day option outranks it here",
          "Accepts Apollo Health Shield's dental rider",
        ],
        demotedForReliability: false,
        scoreComponents: { rating: 0.95, distance: 0.88, availability: 0.35, price: 0.65, reliability: 0.85 },
      },
      {
        providerId: SMILE_CARE_JUNCTION_PROVIDER_ID,
        name: "Smile Care Junction",
        rank: 3,
        score: 0.42,
        reasons: [
          "Previously no-showed on a scheduled household appointment (14 Nov 2025), demoted despite being available sooner than #2",
          "2.4 km away, the furthest of the three",
          "Rated 4.2/5",
          "Slot open tomorrow morning",
        ],
        demotedForReliability: true,
        scoreComponents: { rating: 0.7, distance: 0.55, availability: 0.8, price: 0.75, reliability: 0.1 },
      },
    ],
    narrative:
      "QuickCare Dental Walk-in tops the list because Aarav's reported pain escalates this to urgent, a same-day slot outweighs Bright Smiles Dental's higher rating and existing history, which would otherwise win on a routine visit. Smile Care Junction is available even sooner but is demoted for a documented no-show on file.",
    confidence: 0.83,
    modelTier: "pro",
    promptVersion: "provider-ranking-v1",
    invocationId: "inv-a52-aarav-toothache-1",
    rankedAt: "2026-08-28T15:33:00Z",
  };
}

// ---------------------------------------------------------------------------
// A53 Call Planner — `CallBrief` (frozen E2/E3 handoff shape)
// ---------------------------------------------------------------------------

export interface CallBrief {
  readonly targetProviderId: string;
  readonly personId: string;
  readonly objective: string;
  /** [start, end] ISO instants — the call may never agree to a slot
   * outside this range. */
  readonly dateRange: readonly [string, string];
  readonly priceCeiling: number | null;
  readonly disclosableFacts: readonly string[];
  readonly mustNotAnswer: readonly string[];
  readonly preferredSlots: readonly string[];
  readonly fallbackAcceptable: boolean;
}

// ---------------------------------------------------------------------------
// A54 Voice Call Agent — `CallSpeaker`, `CallTurn`, `CallConversationResult`,
// `CallOutcomeReport`
// ---------------------------------------------------------------------------

export type CallSpeaker = "caller" | "counterparty";

export interface CallTurn {
  readonly speaker: CallSpeaker;
  readonly utterance: string;
  readonly turnIndex: number;
}

export interface CallConversationResult {
  readonly turns: readonly CallTurn[];
  readonly claimedSlot: string | null;
  readonly claimedOutcomeSummary: string;
  readonly outOfBoundsEncountered: boolean;
  readonly requiresHumanCallback: boolean;
}

export interface CallOutcomeReport {
  readonly callId: string;
  readonly targetProviderId: string;
  readonly transcriptSourceDocumentId: string;
  readonly disclosureGiven: boolean;
  readonly claimedSlot: string | null;
  readonly claimedOutcomeSummary: string;
  readonly outOfBoundsEncountered: boolean;
  readonly requiresHumanCallback: boolean;
}

/**
 * Assembles the `CallOutcomeReport` a real orchestration tool
 * (`app.arbitration.voice_call_tool.VoiceCallTool`) produces from a
 * completed `CallConversationResult` plus the two ids only the gated tool
 * itself can populate (`call_id`, `transcript_source_document_id`) —
 * `disclosure_given` is always `true` here for the same reason it is
 * structurally always `true` in the real engine: turn zero of every
 * `CallConversationResult` below is composed by `disclosureOpening`
 * before any counterparty turn exists, never conditionally.
 */
export function outcomeReportFromConversation(
  callId: string,
  transcriptSourceDocumentId: string,
  targetProviderId: string,
  conversation: CallConversationResult,
): CallOutcomeReport {
  return {
    callId,
    targetProviderId,
    transcriptSourceDocumentId,
    disclosureGiven: true,
    claimedSlot: conversation.claimedSlot,
    claimedOutcomeSummary: conversation.claimedOutcomeSummary,
    outOfBoundsEncountered: conversation.outOfBoundsEncountered,
    requiresHumanCallback: conversation.requiresHumanCallback,
  };
}

/**
 * Ports `voice_call_agent._disclosure_opening` verbatim — turn zero of
 * every call this UI ever renders is produced by this pure function, the
 * same way the real engine's is: composed from `CallBrief` fields alone,
 * never phrased by a model. Used directly by the fixtures below so the
 * disclosure line shown on screen is provably the same one the real
 * engine would produce for the same brief, not independently typed prose
 * that could silently drift from it.
 */
export function disclosureOpening(brief: CallBrief): string {
  const preferred = brief.preferredSlots[0];
  const slotClause = preferred
    ? ` I'd like to ask about ${formatDisclosureSlot(preferred)}, if that's available.`
    : "";
  return `Hello, this is an automated assistant calling on behalf of a household, regarding: ${brief.objective}.${slotClause}`;
}

function formatDisclosureSlot(iso: string): string {
  const date = new Date(iso);
  const weekday = date.toLocaleDateString("en-US", { weekday: "long", timeZone: "UTC" });
  const monthDay = date.toLocaleDateString("en-US", { month: "long", day: "2-digit", timeZone: "UTC" });
  const time = date.toLocaleTimeString("en-US", { hour: "2-digit", minute: "2-digit", hour12: true, timeZone: "UTC" });
  return `${weekday} ${monthDay} at ${time}`;
}

export interface CallConnectionAttempt {
  readonly attemptedAt: string;
  readonly targetProviderId: string;
  readonly targetProviderName: string;
  readonly result: "no_answer" | "connected";
}

export interface ConciergeCallRecord {
  readonly callId: string;
  readonly transcriptSourceDocumentId: string;
  readonly brief: CallBrief;
  readonly conversation: CallConversationResult;
  readonly outcomeReport: CallOutcomeReport;
}

function buildCallRecord(
  callId: string,
  brief: CallBrief,
  turns: readonly CallTurn[],
  claimedSlot: string | null,
  claimedOutcomeSummary: string,
  outOfBoundsEncountered: boolean,
  requiresHumanCallback: boolean,
): ConciergeCallRecord {
  const transcriptSourceDocumentId = `sourcedoc-${callId}`;
  const conversation: CallConversationResult = {
    turns,
    claimedSlot,
    claimedOutcomeSummary,
    outOfBoundsEncountered,
    requiresHumanCallback,
  };
  return {
    callId,
    transcriptSourceDocumentId,
    brief,
    conversation,
    outcomeReport: outcomeReportFromConversation(callId, transcriptSourceDocumentId, brief.targetProviderId, conversation),
  };
}

// --- Scenario A: Aarav's toothache — adapts, then succeeds ----------------

export function getAaravToothacheCallBrief(): CallBrief {
  return {
    targetProviderId: QUICKCARE_PROVIDER_ID,
    personId: AARAV_ID,
    objective: "book a same-day or next-available dentist appointment for Aarav, who has had a sore tooth since Tuesday",
    dateRange: ["2026-08-28T16:00:00Z", "2026-08-30T18:00:00Z"],
    priceCeiling: 2500,
    disclosableFacts: [
      "patient's first name is Aarav",
      "patient is 11 years old",
      "insurance: Apollo Health Shield, dental rider active",
      "reason for visit: tooth pain since Tuesday",
    ],
    mustNotAnswer: ["home address", "payment card details", "other household members' medical history"],
    preferredSlots: ["2026-08-28T16:30:00Z", "2026-08-28T17:15:00Z"],
    fallbackAcceptable: true,
  };
}

export function getAaravToothacheCall(): ConciergeCallRecord {
  const brief = getAaravToothacheCallBrief();
  const opening = disclosureOpening(brief);
  const turns: readonly CallTurn[] = [
    { speaker: "caller", utterance: opening, turnIndex: 0 },
    {
      speaker: "counterparty",
      utterance:
        "Thanks for calling QuickCare Dental. Let me just check the book... ah, 4:30 was taken about ten minutes ago, sorry. I do have 5:15 this evening free, or first thing tomorrow at 9 if this evening's too soon.",
      turnIndex: 1,
    },
    {
      speaker: "caller",
      utterance: "5:15 this evening works well for us, let's get Aarav booked in for that, thank you.",
      turnIndex: 2,
    },
  ];
  return buildCallRecord(
    "call-a54-aarav-toothache-1",
    brief,
    turns,
    "2026-08-28T17:15:00Z",
    "Booked with QuickCare Dental Walk-in for 2026-08-28T17:15:00Z.",
    false,
    false,
  );
}

export function getAaravToothacheVerification(): VerificationResult {
  const call = getAaravToothacheCall();
  return {
    callId: call.callId,
    targetProviderId: QUICKCARE_PROVIDER_ID,
    verified: true,
    discrepancies: [],
    requiresHumanCallback: false,
    explanation:
      "Disclosure was confirmed on turn zero; the call named the authorised provider (QuickCare Dental Walk-in); the claimed slot (28 Aug, 5:15 PM) falls inside the authorised date range and is one of the two preferred slots the household approved, nothing to flag.",
    confidence: 0.97,
    modelTier: "pro",
    promptVersion: "confirmation-verifier-v1",
    invocationId: "inv-a55-aarav-toothache-1",
    verifiedAt: "2026-08-28T17:22:00Z",
  };
}

// --- Scenario B: Dadi's routine cleaning — escalates on an out-of-scope question

export function getDadiCleaningCallBrief(): CallBrief {
  return {
    targetProviderId: BRIGHT_SMILES_PROVIDER_ID,
    personId: DADI_ID,
    objective: "book Dadi in for a routine six-month dental cleaning",
    dateRange: ["2026-08-31T00:00:00Z", "2026-09-06T18:00:00Z"],
    priceCeiling: 1500,
    disclosableFacts: [
      "patient's first name is Kamala (Dadi)",
      "patient is a returning senior patient",
      "reason for visit: routine six-month cleaning",
      "insurance: Apollo Health Shield family floater",
    ],
    mustNotAnswer: ["date of birth", "home address", "payment card details", "other household members' medical history"],
    preferredSlots: ["2026-09-02T10:00:00Z", "2026-09-03T10:00:00Z"],
    fallbackAcceptable: true,
  };
}

export function getDadiCleaningCall(): ConciergeCallRecord {
  const brief = getDadiCleaningCallBrief();
  const opening = disclosureOpening(brief);
  const turns: readonly CallTurn[] = [
    { speaker: "caller", utterance: opening, turnIndex: 0 },
    {
      speaker: "counterparty",
      utterance:
        "Hi there, happy to help. Before I book anything, I'll need her date of birth for our senior patient file, is that alright?",
      turnIndex: 1,
    },
    {
      speaker: "caller",
      utterance: "I don't have that information to hand, let me take a message and someone will confirm with you.",
      turnIndex: 2,
    },
  ];
  return buildCallRecord(
    "call-a54-dadi-cleaning-1",
    brief,
    turns,
    null,
    "Bright Smiles Dental asked something outside the disclosable facts list ('her date of birth for our senior patient file'), took a message instead of guessing.",
    false,
    true,
  );
}

export function getDadiCleaningVerification(): VerificationResult {
  const call = getDadiCleaningCall();
  return {
    callId: call.callId,
    targetProviderId: BRIGHT_SMILES_PROVIDER_ID,
    verified: false,
    discrepancies: ["no slot was claimed booked in this outcome report, there is nothing to record"],
    requiresHumanCallback: true,
    explanation:
      "No slot was confirmed on this call, the front desk's question fell outside what was pre-authorised to disclose, and the agent took a message rather than guess. There is nothing to verify as a booking.",
    confidence: 1.0,
    modelTier: "deterministic",
    promptVersion: "confirmation-verifier-v1",
    invocationId: "inv-a55-dadi-cleaning-1",
    verifiedAt: "2026-08-31T09:05:00Z",
  };
}

export function getDadiCleaningFallback(): FallbackDecision {
  const call = getDadiCleaningCall();
  return {
    action: "escalate",
    reasoning:
      "Single attempt to Bright Smiles Dental ended in a question outside pre-authorised disclosure (Dadi's date of birth), rather than retry blind, this needs a household member's decision on how much to share.",
    retryAfter: null,
    escalationPayload: {
      actionType: "concierge.call_outcome.escalate",
      summary:
        "Could not complete Dadi's six-month cleaning booking with Bright Smiles Dental, the front desk asked for her date of birth, which wasn't pre-authorised to share. A message was left; someone should call back directly or approve sharing it.",
      riskTier: "R2",
      evidenceBundle: {
        proposedAction: "Escalate Dadi's dental booking attempt to a household member",
        reasoning:
          "The call reached a real, unanswerable request rather than a technical failure, continuing to guess or retry without a human decision would either fabricate an answer or repeat the same dead end.",
        evidenceConsulted: [
          "Call transcript turn 1: front desk asked for Dadi's date of birth",
          "CallBrief.mustNotAnswer included 'date of birth', never disclosed",
          "No slot was claimed or verified, call_id " + call.callId,
        ],
        confidence: 0.92,
        consequenceIfWrong:
          "If shared without asking, Dadi's date of birth would be given to a third party without explicit household approval, a real privacy/consent step, not a rubber stamp.",
      },
      relatedNodeId: "obligation-book-dadi-dentist-cleaning",
    },
  };
}

// --- Scenario C: Aarav's routine follow-up — retry, then a real, caught mismatch

export function getAaravFollowupCallBrief(): CallBrief {
  return {
    targetProviderId: SUNRISE_FAMILY_DENTAL_PROVIDER_ID,
    personId: AARAV_ID,
    objective: "book Aarav's routine six-month dental follow-up",
    dateRange: ["2026-09-01T00:00:00Z", "2026-09-06T18:00:00Z"],
    priceCeiling: 2000,
    disclosableFacts: [
      "patient's first name is Aarav",
      "patient is 11 years old",
      "reason for visit: routine six-month follow-up",
      "insurance: Apollo Health Shield family floater",
    ],
    mustNotAnswer: ["home address", "payment card details", "other household members' medical history"],
    // Only Wed/Thu 5pm avoid a clash with Aarav's swim class this week —
    // Priya was explicit that nothing else works, hence `fallbackAcceptable: false`.
    preferredSlots: ["2026-09-02T17:00:00Z", "2026-09-03T17:00:00Z"],
    fallbackAcceptable: false,
  };
}

export function getAaravFollowupConnectionAttempt(): CallConnectionAttempt {
  return {
    attemptedAt: "2026-09-01T09:00:00Z",
    targetProviderId: SUNRISE_FAMILY_DENTAL_PROVIDER_ID,
    targetProviderName: "Sunrise Family Dental",
    result: "no_answer",
  };
}

export function getAaravFollowupRetryDecision(): FallbackDecision {
  return {
    action: "retry",
    reasoning:
      "Sunrise Family Dental's line rang out with no answer, spec's retry ladder tries again shortly before treating this as a failed attempt.",
    retryAfter: "2026-09-01T09:15:00Z",
    escalationPayload: null,
  };
}

/**
 * The call that actually connects, after the retry above. **This is the
 * scenario's whole point:** the call itself reports success
 * (`requiresHumanCallback: false`, `outOfBoundsEncountered: false`) —
 * A54's in-call bounds check only ever guards the outer `dateRange`, and
 * Friday 4 Sep genuinely falls inside it. The discrepancy only surfaces
 * one layer up, in `getAaravFollowupVerification` below, which is
 * exactly why A55 exists as an independent, non-bypassable check rather
 * than trusting A54's own report.
 */
export function getAaravFollowupCall(): ConciergeCallRecord {
  const brief = getAaravFollowupCallBrief();
  const opening = disclosureOpening(brief);
  const turns: readonly CallTurn[] = [
    { speaker: "caller", utterance: opening, turnIndex: 0 },
    {
      speaker: "counterparty",
      utterance:
        "Let me look... Wednesday's fully booked and Thursday at 5 is gone too, I'm afraid. I could squeeze him in Friday at 5 instead, would that work?",
      turnIndex: 1,
    },
    {
      speaker: "caller",
      utterance: "Friday at 5 works, let's lock Aarav in for that, thank you.",
      turnIndex: 2,
    },
  ];
  return buildCallRecord(
    "call-a54-aarav-followup-1",
    brief,
    turns,
    "2026-09-04T17:00:00Z",
    "Booked with Sunrise Family Dental for 2026-09-04T17:00:00Z.",
    false,
    false,
  );
}

export function getAaravFollowupVerification(): VerificationResult {
  const call = getAaravFollowupCall();
  const verdict = verifyCallOutcome(call.brief, call.outcomeReport);
  return {
    callId: call.callId,
    targetProviderId: SUNRISE_FAMILY_DENTAL_PROVIDER_ID,
    verified: verdict.verified,
    discrepancies: verdict.discrepancies,
    requiresHumanCallback: verdict.requiresHumanCallback,
    explanation:
      "The call itself reported success and never flagged an out-of-bounds moment, but the household was explicit that only Wednesday or Thursday at 5pm work this week (swim class conflicts with anything else), and Friday was not one of those two. The call's own bounds check only guards the outer date range, not this specific constraint, which is exactly why this independent check exists.",
    confidence: 1.0,
    modelTier: "deterministic",
    promptVersion: "confirmation-verifier-v1",
    invocationId: "inv-a55-aarav-followup-1",
    verifiedAt: "2026-09-01T09:20:00Z",
  };
}

export function getAaravFollowupFallback(): FallbackDecision {
  return {
    action: "escalate",
    reasoning:
      "Sunrise Family Dental confirmed a slot on the call, but it doesn't match either of the two times the household said are actually workable this week, a live discrepancy, not a call failure, so a person should decide whether Friday actually works or the household wants another attempt with tighter authorised bounds.",
    retryAfter: null,
    escalationPayload: {
      actionType: "concierge.call_outcome.escalate",
      summary:
        "Sunrise Family Dental offered Friday 4 Sep at 5pm for Aarav's routine follow-up, the call agent accepted it, but that's not one of the two windows (Wed/Thu 5pm) the household said were the only ones that fit around swim class, and no other time was pre-authorised. Nothing has been booked or recorded.",
      riskTier: "R2",
      evidenceBundle: {
        proposedAction: "Escalate Aarav's routine follow-up booking discrepancy to a household member",
        reasoning:
          "A54's own bounds check only enforces the outer authorised date range; it does not know the household's specific swim-class constraint, which only A55's independent, stricter check against `preferredSlots`/`fallbackAcceptable` catches.",
        evidenceConsulted: [
          "Call transcript: Sunrise offered Friday 4 Sep 5pm after Wed/Thu were both unavailable",
          "CallBrief.preferredSlots: Wed 2 Sep 5pm, Thu 3 Sep 5pm only; fallbackAcceptable=false",
          "A55 structural check: Friday is not among the preferred slots and fallback is disallowed for this call",
        ],
        confidence: 0.95,
        consequenceIfWrong: "If Friday is booked anyway without checking, Aarav may miss swim class or the appointment may need to be cancelled last-minute.",
      },
      relatedNodeId: "obligation-book-aarav-dentist-followup",
    },
  };
}

// ---------------------------------------------------------------------------
// A55 Confirmation Verifier — `VerificationVerdict`, `VerificationResult`
// ---------------------------------------------------------------------------

export interface VerificationVerdict {
  readonly verified: boolean;
  readonly discrepancies: readonly string[];
  readonly requiresHumanCallback: boolean;
}

export interface VerificationResult {
  readonly callId: string;
  readonly targetProviderId: string;
  readonly verified: boolean;
  readonly discrepancies: readonly string[];
  readonly requiresHumanCallback: boolean;
  readonly explanation: string;
  readonly confidence: number;
  readonly modelTier: "pro" | "deterministic";
  readonly promptVersion: string;
  readonly invocationId: string;
  readonly verifiedAt: string;
}

/**
 * A line-for-line port of `backend/app/agents/concierge/verification.py`'s
 * `verify_call_outcome` — the deterministic core of Gate 10's single most
 * safety-critical guarantee. Kept as real, callable logic here (not just
 * asserted in fixture data) so `getAaravFollowupVerification`'s
 * discrepancy is provably the real function's output for that call's
 * exact brief/report, not independently-typed prose that could drift
 * from what the backend would actually decide. See that module's own
 * docstring for the full rationale each check below mirrors.
 */
export function verifyCallOutcome(brief: CallBrief, report: CallOutcomeReport): VerificationVerdict {
  if (!report.disclosureGiven) {
    return {
      verified: false,
      discrepancies: [
        "disclosure_given is False, the automated-assistant disclosure was never confirmed; this is a hard failure per spec §23 and verification stops here, before any further check runs",
      ],
      requiresHumanCallback: true,
    };
  }

  const discrepancies: string[] = [];

  if (report.targetProviderId !== brief.targetProviderId) {
    discrepancies.push(
      `call outcome names provider '${report.targetProviderId}', but the brief authorised only '${brief.targetProviderId}'`,
    );
  }

  if (report.outOfBoundsEncountered) {
    discrepancies.push(
      "out_of_bounds_encountered is True, the call reported an out-of-bounds request, and CallOutcomeReport carries no field proving it was safely declined or resolved, so this is never treated as resolved",
    );
  }

  if (report.claimedSlot === null) {
    discrepancies.push("no slot was claimed booked in this outcome report, there is nothing to record");
    return { verified: false, discrepancies, requiresHumanCallback: true };
  }

  const claimedMs = new Date(report.claimedSlot).getTime();
  const [startIso, endIso] = brief.dateRange;
  const startMs = new Date(startIso).getTime();
  const endMs = new Date(endIso).getTime();
  if (!(startMs <= claimedMs && claimedMs <= endMs)) {
    discrepancies.push(
      `claimed_slot ${report.claimedSlot} falls outside the authorised date_range (${startIso} to ${endIso})`,
    );
  }

  const isPreferred = brief.preferredSlots.some((slot) => new Date(slot).getTime() === claimedMs);
  if (!isPreferred && !brief.fallbackAcceptable) {
    discrepancies.push(
      `claimed_slot ${report.claimedSlot} is not one of the authorised preferred_slots, and fallback_acceptable is False for this call`,
    );
  }

  if (discrepancies.length > 0) {
    return { verified: false, discrepancies, requiresHumanCallback: true };
  }
  return { verified: true, discrepancies: [], requiresHumanCallback: false };
}

// ---------------------------------------------------------------------------
// The graph-write boundary — "verified, or it does not exist"
// (`app.tools.booking_write_tool`) — `VerifiedBooking`, `BookingOutcome`
// ---------------------------------------------------------------------------

export interface VerifiedBooking {
  readonly callId: string;
  readonly obligationId: string;
  readonly personId: string;
  readonly targetProviderId: string;
  readonly transcriptSourceDocumentId: string;
  readonly confirmedSlot: string;
  readonly confirmedPrice: number | null;
  readonly attributionTags: readonly string[];
  readonly verifiedByAgent: string;
  readonly verifiedAt: string;
}

export type BookingOutcome =
  | { readonly kind: "confirmed"; readonly booking: VerifiedBooking; readonly verification: VerificationResult }
  | { readonly kind: "not_recorded"; readonly verification: VerificationResult; readonly outcomeReport: CallOutcomeReport };

/**
 * Ports `booking_write_tool.verified_booking_from_verification`'s real
 * guard: a `VerifiedBooking` can only ever be produced from a genuinely
 * positive `VerificationResult` with a real confirmed slot — anything
 * short of that returns `"not_recorded"`, never a booking with a
 * carelessly-set flag. This is this file's own structural proof of Gate
 * 10's CTO review question ("is there any code path writing a booking
 * without verification?") for the frontend's display logic: there is no
 * branch here that can produce `{ kind: "confirmed" }` from an unverified
 * or slot-less input — see `concierge.test.ts` for the adversarial proof.
 */
export function buildBookingOutcome(args: {
  readonly verification: VerificationResult;
  readonly outcomeReport: CallOutcomeReport;
  readonly obligationId: string;
  readonly personId: string;
  readonly confirmedPrice: number | null;
  readonly attributionTags: readonly string[];
  readonly verifiedByAgent: string;
}): BookingOutcome {
  const { verification, outcomeReport } = args;
  if (!verification.verified || outcomeReport.claimedSlot === null) {
    return { kind: "not_recorded", verification, outcomeReport };
  }
  return {
    kind: "confirmed",
    verification,
    booking: {
      callId: verification.callId,
      obligationId: args.obligationId,
      personId: args.personId,
      targetProviderId: verification.targetProviderId,
      transcriptSourceDocumentId: outcomeReport.transcriptSourceDocumentId,
      confirmedSlot: outcomeReport.claimedSlot,
      confirmedPrice: args.confirmedPrice,
      attributionTags: args.attributionTags,
      verifiedByAgent: args.verifiedByAgent,
      verifiedAt: verification.verifiedAt,
    },
  };
}

export function getAaravToothacheBookingOutcome(): BookingOutcome {
  const call = getAaravToothacheCall();
  return buildBookingOutcome({
    verification: getAaravToothacheVerification(),
    outcomeReport: call.outcomeReport,
    obligationId: "obligation-book-aarav-dentist-toothache",
    personId: AARAV_ID,
    confirmedPrice: 1800,
    // No visit has happened yet at the point of booking — no reliability
    // signal exists to attribute. Populated for real only after the
    // appointment happens, matching ADR-016's formal vocabulary.
    attributionTags: [],
    verifiedByAgent: "A55",
  });
}

export function getDadiCleaningBookingOutcome(): BookingOutcome {
  const call = getDadiCleaningCall();
  return buildBookingOutcome({
    verification: getDadiCleaningVerification(),
    outcomeReport: call.outcomeReport,
    obligationId: "obligation-book-dadi-dentist-cleaning",
    personId: DADI_ID,
    confirmedPrice: null,
    attributionTags: [],
    verifiedByAgent: "A55",
  });
}

export function getAaravFollowupBookingOutcome(): BookingOutcome {
  const call = getAaravFollowupCall();
  return buildBookingOutcome({
    verification: getAaravFollowupVerification(),
    outcomeReport: call.outcomeReport,
    obligationId: "obligation-book-aarav-dentist-followup",
    personId: AARAV_ID,
    confirmedPrice: null,
    attributionTags: [],
    verifiedByAgent: "A55",
  });
}

// ---------------------------------------------------------------------------
// A56 Fallback Coordinator — `FallbackAction`, `FallbackEscalationPayload`,
// `FallbackDecision`
// ---------------------------------------------------------------------------

export type FallbackAction = "retry" | "web_booking_fallback" | "escalate";

export interface FallbackEscalationPayload {
  readonly actionType: string;
  readonly summary: string;
  readonly riskTier: RiskTier;
  readonly evidenceBundle: EvidenceBundle;
  readonly relatedNodeId: string | null;
}

export interface FallbackDecision {
  readonly action: FallbackAction;
  readonly reasoning: string;
  readonly retryAfter: string | null;
  readonly escalationPayload: FallbackEscalationPayload | null;
}

// ---------------------------------------------------------------------------
// The Approval Gate — spec §13.2 Step 4 ("R2/R3 gate... Proceed?"), fires
// before any call is placed, reusing the exact `EvidenceBundle`/`RiskTier`
// shapes the Approval Gate UI (Phase 5) already renders.
// ---------------------------------------------------------------------------

export interface ConciergeCallApproval {
  readonly riskTier: RiskTier;
  readonly evidenceBundle: EvidenceBundle;
}

export function getAaravToothacheApproval(): ConciergeCallApproval {
  return {
    riskTier: "R2",
    evidenceBundle: {
      proposedAction: "Call QuickCare Dental Walk-in (0.8 km away, rated 4.5) to get Aarav seen today for his sore tooth.",
      reasoning:
        "QuickCare ranked #1 for this urgent request, nearest, same-day availability, and within insurance. Bright Smiles Dental (Aarav's regular clinic) is rated higher but can't be seen for 3-4 days, which doesn't fit a pain complaint.",
      evidenceConsulted: [
        "A50 clarification: pain reported since Tuesday → elevated urgency",
        "A52 ranking: QuickCare #1 (score 0.88) vs Bright Smiles #2 (0.71) vs Smile Care Junction #3 (0.42, demoted for a no-show)",
        "Household schedule: Aarav free from 4:30pm today",
        "Apollo Health Shield accepts QuickCare's dental rider",
      ],
      confidence: 0.86,
      consequenceIfWrong:
        "If QuickCare turns out unsuitable on arrival, nothing has been paid or confirmed yet, the household can redirect to Bright Smiles Dental or Smile Care Junction instead.",
    },
  };
}

// ---------------------------------------------------------------------------
// Progressive transcript reveal — pure, testable timing logic for
// `LiveCallTranscript`'s "turns appearing turn by turn" animation.
// **Honesty, stated once here and again at every call site:** the
// transcript data itself is a real, already-complete fixture — this
// function only computes how many of its turns to *currently render*,
// mirroring the spirit of `lib/graph-animation.ts`'s "arrival" easing for
// Phase 6's live graph growth. It is a presentation animation, not a
// live stream.
// ---------------------------------------------------------------------------

export const TRANSCRIPT_TURN_REVEAL_MS = 900;

export function revealedTurnCount(totalTurns: number, elapsedMs: number, msPerTurn: number = TRANSCRIPT_TURN_REVEAL_MS): number {
  if (totalTurns <= 0) return 0;
  if (elapsedMs < 0) return 0;
  return Math.min(totalTurns, Math.floor(elapsedMs / msPerTurn) + 1);
}
