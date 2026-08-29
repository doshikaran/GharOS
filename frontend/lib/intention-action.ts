/**
 * TypeScript mirrors of the Phase 9 Intention->Action Converter's real
 * output shapes (PHASES.md Phase 9, E4 work item — "diagnosis display with
 * correction affordance; friction profile view"), plus the real
 * `CHARACTERIZES`-friction-profile write logic ported from
 * `friction_profile.py`.
 *
 * Source of truth, read directly rather than guessed at:
 *   - `backend/app/agents/intention_action/types.py` — `BlockerType`,
 *     `BlockerDiagnosis`, `DiagnosisCorrection`, A22/A24/A25/A26's own
 *     request/result shapes.
 *   - `backend/app/agents/intention_action/friction_profile.py` — the real
 *     `CHARACTERIZES` write/increment/supersede logic this file's
 *     `applyDiagnosisCorrection` ports (see that function's own doc
 *     comment for the one deliberate simplification: this module tracks
 *     only the *current* version of each friction `Pattern`, matching what
 *     `backend/tests/test_friction_profile.py`'s own `FakeGraphReader`
 *     wiring treats as "this person's existing CHARACTERIZES neighbour" —
 *     a superseded version recedes from the current view exactly like a
 *     superseded `Obligation` does elsewhere in this codebase).
 *   - `backend/app/agents/intention_action/schedule_parsing.py` — ported
 *     separately, in full, as `lib/schedule-availability.ts`.
 *   - `docs/adr/015-availability-and-friction-profile.md` — why the
 *     friction profile is `Pattern`/`CHARACTERIZES`, not a bespoke shape.
 *
 * Field names are camelCase, following `lib/fair-allocator.ts`'s
 * established fixture/wire-seam convention — every field maps 1:1 to its
 * snake_case Python name.
 *
 * **DATA-LOADING BOUNDARY (this phase's own brief, this file's documented
 * seam).** None of A23-A26's output shapes have a REST endpoint this phase
 * — no role built one; Phase 9's backend work was agents only. Every
 * `get*()` fixture function below is a fixture-backed seam, exactly the
 * precedent `lib/fair-allocator.ts` and `lib/ledger.ts` set in Phases 7-8.
 * **The one exception:** real household member names/ids and Dadi's real
 * `SCHEDULE`-kind constraint come from the live `/graph/snapshot` (see
 * `components/intention-action/IntentionActionExplorer.tsx`, which fetches
 * it and passes real `GraphNode[]` down) — this file's fixtures reference
 * those same real node ids directly (`PRIYA_ID`, `AARAV_ID`, `DADI_ID`,
 * `MAYA_ID`, `DADI_NAP_CONSTRAINT_ID`) rather than inventing parallel ones.
 *
 * Continuous with `backend/seeds/demo_household.py` and every prior
 * phase's fixtures — the same household (Priya, Aarav, Dadi, Maya), never
 * a second, disconnected demo family. No `CHARACTERIZES` edge exists in
 * the live seed yet (confirmed directly against `demo_household.py` before
 * writing this file) — ADR-015 added the edge type this phase, but no
 * role has written one to the live graph yet, so the entire friction
 * profile below is fixture data, clearly seamed as such.
 */

import { personAvailabilityForWindow, type ScheduleConstraintInput } from "./schedule-availability";

// ---------------------------------------------------------------------------
// Real node ids this fixture data is built on top of (gharos-standards: no
// magic values re-typed at each call site) — mirrors `lib/fair-allocator.ts`.
// ---------------------------------------------------------------------------

export const PRIYA_ID = "person-priya";
export const AARAV_ID = "person-aarav";
export const DADI_ID = "person-dadi";
export const MAYA_ID = "person-maya";

/** Real, live `constraint-dadi-nap` (`backend/seeds/demo_household.py`,
 * migrated to ADR-015's formal schema this phase) — used directly for the
 * window-blocker demo's person-availability half. */
export const DADI_NAP_CONSTRAINT_ID = "constraint-dadi-nap";

/** Reference time this fixture set is built around — matches
 * `backend/seeds/demo_household.py`'s own `NOW` exactly, so "124 days
 * stale" and every other relative figure below is checkable against it. */
export const SEED_NOW = "2026-08-22T09:00:00Z";

// ---------------------------------------------------------------------------
// Shared taxonomy — `types.BlockerType`, the six-type closed taxonomy spec
// §9.3 Stage 2 names explicitly, and no others.
// ---------------------------------------------------------------------------

export type BlockerType =
  | "information"
  | "decision"
  | "window"
  | "first_step_ambiguity"
  | "dependency"
  | "aversion";

export const BLOCKER_TYPES: readonly BlockerType[] = [
  "information",
  "decision",
  "window",
  "first_step_ambiguity",
  "dependency",
  "aversion",
];

export interface BlockerTypeMeta {
  readonly label: string;
  readonly shortDescription: string;
}

/** spec §9.3's own six definitions, verbatim in spirit — the taxonomy made
 * legible, not just a raw enum value on screen. */
export const BLOCKER_TYPE_META: Readonly<Record<BlockerType, BlockerTypeMeta>> = {
  information: {
    label: "Information blocker",
    shortDescription: "A needed fact is missing, a number, account, policy, or last-service date.",
  },
  decision: {
    label: "Decision blocker",
    shortDescription: "An unmade choice sits upstream of the task.",
  },
  window: {
    label: "Window blocker",
    shortDescription: "Action is only possible when the person is never actually free.",
  },
  first_step_ambiguity: {
    label: "First-step ambiguity",
    shortDescription: "The person doesn't know the actual first concrete action.",
  },
  dependency: {
    label: "Dependency blocker",
    shortDescription: "Something else has to happen first.",
  },
  aversion: {
    label: "Aversion blocker",
    shortDescription: "The person systematically avoids this modality, e.g. never makes calls.",
  },
};

// ---------------------------------------------------------------------------
// A22 — Intention Capture
// ---------------------------------------------------------------------------

export interface StaleObligationDetection {
  readonly obligationId: string;
  readonly title: string;
  readonly reason: string;
  readonly daysStale: number;
  readonly thresholdDays: number;
  /** ISO 8601. */
  readonly detectedAt: string;
}

// ---------------------------------------------------------------------------
// A23 — Blocker Diagnosis
// ---------------------------------------------------------------------------

export interface BlockerDiagnosis {
  readonly obligationId: string;
  readonly personId: string;
  readonly blockerType: BlockerType;
  /** A complete, standalone, human-readable statement of the diagnosis —
   * first-class, never a fragment that only makes sense alongside
   * `reasoning`/`evidence` (`types.BlockerDiagnosis.diagnosis_text`'s own
   * contract, and PHASES.md Gate 9's literal wording). */
  readonly diagnosisText: string;
  readonly evidence: readonly string[];
  readonly confidence: number;
  readonly consideredAlternativeTypes: readonly BlockerType[];
  readonly isRediagnosis: boolean;
  readonly supersededDiagnosisType: BlockerType | null;
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
  /** ISO 8601. */
  readonly diagnosedAt: string;
}

export interface DiagnosisCorrection {
  readonly obligationId: string;
  readonly personId: string;
  readonly originalDiagnosis: BlockerDiagnosis;
  readonly correctedBlockerType: BlockerType;
  /** The human's own words explaining the correction — never discarded,
   * never paraphrased away (`types.DiagnosisCorrection.correction_note`). */
  readonly correctionNote: string;
  readonly correctedBy: string;
  /** ISO 8601. */
  readonly correctedAt: string;
}

// ---------------------------------------------------------------------------
// A24 — Unblocker / Preparation
// ---------------------------------------------------------------------------

export interface InformationFetchResult {
  readonly obligationId: string;
  readonly missingFactDescription: string;
  /** `false` (never a fabricated `factText`) whenever the real graph query
   * would return nothing — Gate 9's "Information blocker -> fact fetched"
   * made honest about the negative case too. */
  readonly fetched: boolean;
  readonly factText: string | null;
  readonly confidence: number;
  readonly modelTier: "flash";
  readonly promptVersion: string | null;
  readonly invocationId: string;
}

export interface DecisionNarrowingResult {
  readonly obligationId: string;
  /** Always two real, distinct, mutually exclusive options — never the
   * decision left open, and never a third "it depends" escape hatch. */
  readonly optionA: string;
  readonly optionB: string;
  readonly framingText: string;
  readonly reasoning: string;
  readonly confidence: number;
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
}

export type AversionModality = "call" | "message" | "in_person" | "email" | "app_form";

export const AVERSION_MODALITY_LABEL: Readonly<Record<AversionModality, string>> = {
  call: "Phone call",
  message: "Written message",
  in_person: "In person",
  email: "Email",
  app_form: "App / online form",
};

export interface ModalitySwitchResult {
  readonly obligationId: string;
  /** Always a real, different modality than `fromModality` — Gate 9's
   * "Aversion blocker -> modality switched" enforced structurally: this
   * type has no field that could hold an unchanged pair, and every fixture
   * below is asserted distinct in `intention-action.test.ts`. */
  readonly fromModality: AversionModality;
  readonly toModality: AversionModality;
  readonly preDraftedText: string;
  readonly reasoning: string;
  readonly confidence: number;
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
}

// ---------------------------------------------------------------------------
// A25 — Window Scheduling
// ---------------------------------------------------------------------------

export type { AvailabilityVerdict } from "./schedule-availability";
import type { AvailabilityVerdict } from "./schedule-availability";

export type CounterpartyAvailabilityVerdict = "available" | "unavailable" | "cannot_determine";
export type HistoricalLikelihoodVerdict = "likely" | "unlikely" | "insufficient_data";

export interface WindowCandidateEvaluation {
  /** `[startIso, endIso]`. */
  readonly window: readonly [string, string];
  readonly personAvailability: AvailabilityVerdict;
  readonly counterpartyAvailability: CounterpartyAvailabilityVerdict | null;
  readonly historicalLikelihood: HistoricalLikelihoodVerdict;
  readonly overallRecommended: boolean;
  readonly reasoning: string;
}

export interface WindowFindingResult {
  readonly obligationId: string;
  readonly personId: string;
  readonly evaluations: readonly WindowCandidateEvaluation[];
  /** `null` only when no candidate cleared the hard-block/unavailable
   * exclusion — never a fallback guess. */
  readonly bestWindow: readonly [string, string] | null;
  readonly confidence: number;
  readonly modelTier: "deterministic" | "flash" | "pro";
}

// ---------------------------------------------------------------------------
// A26 — Slippage Analyst
// ---------------------------------------------------------------------------

export interface UnblockingAttempt {
  readonly attemptNumber: number;
  readonly diagnosis: BlockerDiagnosis;
  readonly actionTaken: string;
  readonly outcome: "failed" | "succeeded";
  /** ISO 8601. */
  readonly attemptedAt: string;
}

export interface DelegateCandidate {
  readonly personId: string;
  readonly displayName: string;
  readonly relevantCapabilityNote: string;
}

export interface SlippageReDiagnosis {
  readonly likelyBlockerType: BlockerType;
  readonly reasoning: string;
  readonly confidence: number;
  readonly changedFromPrior: boolean;
}

export type EscalationOptionKind = "drop" | "delegate" | "pay";

export interface EscalationOption {
  readonly kind: EscalationOptionKind;
  readonly description: string;
  /** Populated only for `kind === "delegate"`. */
  readonly candidatePersonId: string | null;
  /** Populated only for `kind === "pay"`, and only when a real market-rate
   * hint grounds a number — `null` otherwise, never a fabricated figure. */
  readonly estimatedCost: number | null;
}

export interface SlippageAnalysisResult {
  readonly obligationId: string;
  readonly personId: string;
  readonly attemptCount: number;
  readonly threshold: number;
  readonly escalationTriggered: boolean;
  readonly reDiagnosis: SlippageReDiagnosis | null;
  readonly escalationOptions: readonly EscalationOption[];
  readonly messageText: string;
  readonly confidence: number;
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
}

// ---------------------------------------------------------------------------
// Friction profile — ADR-015's `CHARACTERIZES` edge (`Pattern -> Person`),
// ported from `friction_profile.py`.
// ---------------------------------------------------------------------------

/** TypeScript mirror of the real `contracts.graph_types.Pattern` fields
 * this module cares about, narrowed to the friction-profile use (a real
 * `Pattern` also carries `contributing_outcome_ids`, irrelevant here). */
export interface FrictionPattern {
  readonly id: string;
  readonly personId: string;
  readonly blockerType: BlockerType;
  readonly description: string;
  readonly supportCount: number;
  readonly confidence: number;
  /** ISO 8601. */
  readonly createdAt: string;
}

const PATTERN_DESCRIPTION_PREFIX = "Friction pattern";
const DESCRIPTION_RE = /^Friction pattern \(([a-z_]+)\), /;

const BASE_CONFIDENCE = 0.5;
const CONFIDENCE_PER_SUPPORT = 0.1;
const MAX_CONFIDENCE = 0.9;

/** Mirrors `friction_profile._pattern_confidence` exactly — grows with real
 * accumulated evidence, never starts near-certain from one correction,
 * never reaches false certainty. */
export function patternConfidence(supportCount: number): number {
  return Math.min(BASE_CONFIDENCE + CONFIDENCE_PER_SUPPORT * supportCount, MAX_CONFIDENCE);
}

function buildPatternDescription(args: {
  readonly blockerType: BlockerType;
  readonly personDisplayName: string;
  readonly detail: string;
}): string {
  return `${PATTERN_DESCRIPTION_PREFIX} (${args.blockerType}), ${args.personDisplayName}: ${args.detail}`;
}

/** Mirrors `friction_profile.extract_blocker_type_from_pattern` exactly —
 * `null` for any pattern not written by this module's own convention (e.g.
 * the live seed's `pattern-priya-does-grocery-runs`, an A10 Pattern Miner
 * regularity unrelated to blocker diagnosis), never throws. */
export function extractBlockerTypeFromPattern(description: string): BlockerType | null {
  const match = DESCRIPTION_RE.exec(description);
  if (match === null) return null;
  const candidate = match[1];
  return (BLOCKER_TYPES as readonly string[]).includes(candidate) ? (candidate as BlockerType) : null;
}

/** Mirrors `friction_profile.find_matching_pattern` — the real, *current*
 * friction `Pattern` for `personId`/`blockerType`, if one exists. */
export function findMatchingPattern(
  patterns: readonly FrictionPattern[],
  personId: string,
  blockerType: BlockerType,
): FrictionPattern | null {
  return patterns.find((p) => p.personId === personId && p.blockerType === blockerType) ?? null;
}

/** Every `FrictionPattern` `CHARACTERIZES`-linked to one person — mirrors
 * `friction_profile.summarise_for_person`'s selection, returned structured
 * (a component renders it, rather than pre-formatting text here). */
export function patternsForPerson(
  patterns: readonly FrictionPattern[],
  personId: string,
): readonly FrictionPattern[] {
  return patterns.filter((p) => p.personId === personId);
}

export interface ApplyCorrectionResult {
  readonly patterns: readonly FrictionPattern[];
  readonly writtenPattern: FrictionPattern;
  /** Whether this correction incremented an existing pattern (real,
   * accumulating evidence) vs. created a brand-new one (first evidence of
   * this blocker type for this person) — surfaced so the UI can say which
   * happened, rather than leaving it implicit. */
  readonly wasIncrement: boolean;
}

/**
 * Ports `friction_profile.apply_diagnosis_correction`'s real logic: find
 * this person's existing `blockerType` pattern (if any) and supersede it
 * with `support_count + 1`, or create a brand-new one at `support_count =
 * 1`. Pure and deterministic — no backend write happens here (this phase
 * has no live write endpoint for this; see this file's module doc comment)
 * — the caller (`IntentionActionExplorer`) is what makes the result
 * visible as new component state, which is what actually satisfies Gate
 * 9's "correction updates the friction profile" in this UI.
 *
 * **The one deliberate simplification vs. the real backend**: this
 * function's `patterns` list holds only the *current* version of each
 * (person, blockerType) pattern, never a superseded one alongside its
 * replacement — this is exactly what `find_matching_pattern`'s real
 * `neighbours(person, CHARACTERIZES)` query is shown resolving to in
 * `backend/tests/test_friction_profile.py`'s own `FakeGraphReader` wiring
 * (a superseded `Pattern` recedes from what a caller treats as "this
 * person's existing pattern," even though the graph technically keeps the
 * old `CHARACTERIZES` edge for history) — so this mirrors the real,
 * observable query behaviour, not just the write mechanics.
 */
export function applyDiagnosisCorrection(
  patterns: readonly FrictionPattern[],
  correction: DiagnosisCorrection,
  personDisplayName: string,
): ApplyCorrectionResult {
  const existing = findMatchingPattern(patterns, correction.personId, correction.correctedBlockerType);
  const detail = `${correction.correctionNote} (obligation ${correction.obligationId})`;
  const supportCount = existing === null ? 1 : existing.supportCount + 1;

  const writtenPattern: FrictionPattern = {
    id: `pattern-${correction.personId}-${correction.correctedBlockerType}-v${supportCount}`,
    personId: correction.personId,
    blockerType: correction.correctedBlockerType,
    description: buildPatternDescription({
      blockerType: correction.correctedBlockerType,
      personDisplayName,
      detail,
    }),
    supportCount,
    confidence: patternConfidence(supportCount),
    createdAt: correction.correctedAt,
  };

  const withoutExisting =
    existing === null ? patterns : patterns.filter((p) => p.id !== existing.id);

  return { patterns: [...withoutExisting, writtenPattern], writtenPattern, wasIncrement: existing !== null };
}

// ---------------------------------------------------------------------------
// Fixture ids — new, fixture-only obligations this phase's diagnosis/
// unblock/escalation demos are built on (never in the live `/graph/
// snapshot` — no stale-for-months obligation exists in the live seed to
// ground spec §9.6's demo beat on, and no HTTP write endpoint exists this
// phase to add one for real). Named following `demo_household.py`'s own
// `obligation-<slug>` id convention so they read as the same household's
// obligations, not a second, disconnected family.
// ---------------------------------------------------------------------------

export const TASK_DENTAL_CHECKUP_ID = "obligation-dental-checkup-aarav";
export const TASK_EYE_CHECKUP_ID = "obligation-eye-checkup-dadi";
export const TASK_FIELD_TRIP_PAYMENT_ID = "obligation-field-trip-payment-aarav";
export const TASK_DADI_PHYSIO_ID = "obligation-dadi-physio-escort";

// ---------------------------------------------------------------------------
// Fixture — A22 stale-obligation detection (the demo beat's "before")
// ---------------------------------------------------------------------------

/** Untouched for 124 days (2026-04-20 -> `SEED_NOW`, 2026-08-22) — spec
 * §9.6's demo beat, "a task untouched for four months," made a real,
 * specific number rather than a round narrative figure. */
export function getStaleObligationDetection(): StaleObligationDetection {
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    title: "Book Aarav's dental check-up",
    reason:
      "Open for 124 days with no status change, no linked action, and no scheduled window, the household's own median obligation completes within 9 days of creation.",
    daysStale: 124,
    thresholdDays: 21,
    detectedAt: SEED_NOW,
  };
}

// ---------------------------------------------------------------------------
// Fixture — the dental check-up's full diagnosis history (three real
// attempts: information -> first-step ambiguity -> aversion), the slippage
// escalation it triggers, and the aversion-targeted unblock that actually
// resolves it — the single obligation carrying spec §9.6's whole demo beat.
// ---------------------------------------------------------------------------

function dentalDiagnosisAttempt1(): BlockerDiagnosis {
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    personId: PRIYA_ID,
    blockerType: "information",
    diagnosisText:
      "This is blocked because the clinic's phone number and Aarav's last visit date aren't on hand, Priya has said twice she 'needs to look that up.'",
    evidence: [
      "Priya's message, 9 May: \"I need to find that dentist's number again\"",
      "No last-visit date recorded anywhere in the household's records",
    ],
    confidence: 0.68,
    consideredAlternativeTypes: ["first_step_ambiguity", "aversion"],
    isRediagnosis: false,
    supersededDiagnosisType: null,
    modelTier: "pro",
    promptVersion: "blocker-diagnosis-v3",
    invocationId: "inv-dental-diagnosis-1",
    diagnosedAt: "2026-05-02T11:00:00Z",
  };
}

function dentalDiagnosisAttempt2(): BlockerDiagnosis {
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    personId: PRIYA_ID,
    blockerType: "first_step_ambiguity",
    diagnosisText:
      "Priya now has the clinic's number and Aarav's last visit date, she still hasn't called. She says she \"just hasn't figured out how to start.\" The blocker is not missing information, it's not knowing the actual first action.",
    evidence: [
      "Attempt 1 fetched the number and last-visit date on 2 May; the task still did not happen",
      "Priya's message, 12 Jun: \"I have the number now, I just haven't gotten to it\"",
    ],
    confidence: 0.6,
    consideredAlternativeTypes: ["information", "aversion"],
    isRediagnosis: true,
    supersededDiagnosisType: "information",
    modelTier: "pro",
    promptVersion: "blocker-diagnosis-v3",
    invocationId: "inv-dental-diagnosis-2",
    diagnosedAt: "2026-06-14T09:30:00Z",
  };
}

function dentalDiagnosisAttempt3(): BlockerDiagnosis {
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    personId: PRIYA_ID,
    blockerType: "aversion",
    diagnosisText:
      "This is blocked because Priya avoids phone calls, not because the number was missing or the first step was unclear, the same aversion pattern is already on file for her (seen 3 times before this). Two prior diagnoses treated the symptom, not the cause.",
    evidence: [
      "Friction profile: Priya, aversion (phone calls), seen 3 times",
      "Attempt 1 fetched the number and date directly; the task still did not happen",
      "Attempt 2 named a single concrete first step (\"call and ask for a Saturday slot\"); the task still did not happen",
    ],
    confidence: 0.81,
    consideredAlternativeTypes: ["first_step_ambiguity", "dependency"],
    isRediagnosis: true,
    supersededDiagnosisType: "first_step_ambiguity",
    modelTier: "pro",
    promptVersion: "blocker-diagnosis-v3",
    invocationId: "inv-dental-diagnosis-3",
    diagnosedAt: "2026-08-20T16:00:00Z",
  };
}

/** The dental check-up's full, real attempt history — chronological, never
 * a bare failure count (spec §9.5's own point). */
export function getDentalCheckupAttempts(): readonly UnblockingAttempt[] {
  return [
    {
      attemptNumber: 1,
      diagnosis: dentalDiagnosisAttempt1(),
      actionTaken: "A24 fetched the clinic's phone number and Aarav's last visit date from the household's records.",
      outcome: "failed",
      attemptedAt: "2026-05-02T11:05:00Z",
    },
    {
      attemptNumber: 2,
      diagnosis: dentalDiagnosisAttempt2(),
      actionTaken:
        'A24 pre-staged a single first step: "Call Bright Smiles Dental at the number on file and ask for the next available Saturday slot."',
      outcome: "failed",
      attemptedAt: "2026-06-14T09:35:00Z",
    },
    {
      attemptNumber: 3,
      diagnosis: dentalDiagnosisAttempt3(),
      actionTaken: "Not attempted, A26 escalated after two failed unblocking attempts before a third was tried.",
      outcome: "failed",
      attemptedAt: "2026-08-20T16:05:00Z",
    },
  ];
}

/** The diagnosis this page shows as the dental check-up's *current* state —
 * the third, re-diagnosed one, with its own "the first diagnosis may have
 * been wrong" framing intact. */
export function getDentalCheckupCurrentDiagnosis(): BlockerDiagnosis {
  return dentalDiagnosisAttempt3();
}

/** A26's real slippage analysis at the point of the third failed attempt —
 * Gate 9's "repeat slippage escalates with real options." */
export function getDentalCheckupSlippageAnalysis(): SlippageAnalysisResult {
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    personId: PRIYA_ID,
    attemptCount: 3,
    threshold: 3,
    escalationTriggered: true,
    reDiagnosis: {
      likelyBlockerType: "aversion",
      reasoning:
        "Two prior unblocking attempts (fetching the missing information, then naming a single concrete first step) both removed a plausible-sounding blocker and the task still did not happen, the pattern matches Priya's documented call aversion far better than either prior diagnosis.",
      confidence: 0.81,
      changedFromPrior: true,
    },
    escalationOptions: [
      {
        kind: "drop",
        description:
          "Drop it for now, Aarav's last check-up was 7 months ago; most guidance allows up to a year between routine visits, so this is not urgent.",
        candidatePersonId: null,
        estimatedCost: null,
      },
      {
        kind: "delegate",
        description:
          "Delegate the call to Dadi, she has no documented aversion to phone calls and is home during clinic hours.",
        candidatePersonId: DADI_ID,
        estimatedCost: null,
      },
      {
        kind: "pay",
        description:
          "Pay a local booking service to place the call and confirm a slot on the household's behalf.",
        candidatePersonId: null,
        estimatedCost: 150,
      },
    ],
    messageText:
      "This has slipped 3 times over about 4 months. The real blocker looks like Priya's phone-call aversion, not the earlier information or first-step diagnoses, drop it, delegate it to Dadi, or pay a local agent to book it directly.",
    confidence: 0.81,
    modelTier: "pro",
    promptVersion: "slippage-analyst-v1",
    invocationId: "inv-dental-slippage-1",
  };
}

/** The unblock that actually resolves it — Gate 9's "Aversion blocker ->
 * modality switched," shown as a real before/after. This is what the
 * household's own agent does *instead of* acting on any of the three
 * escalation options above: correctly targeting the real (aversion)
 * blocker resolves it before a human needs to choose drop/delegate/pay. */
export function getDentalCheckupModalitySwitch(): ModalitySwitchResult {
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    fromModality: "call",
    toModality: "message",
    preDraftedText:
      "Hi Bright Smiles Dental, I'd like to book a check-up for my son Aarav (last seen 12 Feb 2026). Do you have anything on a Saturday morning in the next two weeks? Happy to confirm by message., Priya",
    reasoning:
      "Priya's own friction profile shows a repeated call aversion, never a call-content or scheduling problem, switching to a written message removes the actual blocker instead of re-preparing the same call a third time.",
    confidence: 0.83,
    modelTier: "pro",
    promptVersion: "unblocker-modality-switch-v2",
    invocationId: "inv-dental-modality-switch",
  };
}

/** The window the clinic confirmed by reply — spec's own worked example's
 * "30 seconds instead of 15 minutes," made concrete as a real scheduled
 * slot once the actual blocker was gone. */
export function getDentalCheckupWindow(): WindowFindingResult {
  const window: readonly [string, string] = ["2026-08-29T10:00:00Z", "2026-08-29T10:30:00Z"];
  return {
    obligationId: TASK_DENTAL_CHECKUP_ID,
    personId: PRIYA_ID,
    evaluations: [
      {
        window,
        personAvailability: "available",
        counterpartyAvailability: "available",
        historicalLikelihood: "likely",
        overallRecommended: true,
        reasoning:
          "Saturday morning has no conflicting household constraint on file for Priya, the clinic confirmed by return message, and Saturday-morning errands are the household's most reliably completed window.",
      },
    ],
    bestWindow: window,
    confidence: 0.79,
    modelTier: "flash",
  };
}

/** Elapsed real time from the moment the aversion-targeted modality switch
 * was sent to the clinic's confirmed booking — spec §9.6's demo beat made
 * literal, alongside the 124-day "before." */
export const DENTAL_CHECKUP_RESOLUTION_SECONDS = 30;

// ---------------------------------------------------------------------------
// Fixture — the eye check-up: the one obligation this page's real
// correction affordance operates on (item 1/2's connected demo).
// ---------------------------------------------------------------------------

export function getEyeCheckupDiagnosis(): BlockerDiagnosis {
  return {
    obligationId: TASK_EYE_CHECKUP_ID,
    personId: PRIYA_ID,
    blockerType: "information",
    diagnosisText:
      "This is blocked because Dadi's last eye-exam date and the optician's phone number aren't on hand, Priya has said she \"needs to look it up\" twice now.",
    evidence: [
      'Priya\'s message, 15 Aug: "I need to find that eye doctor\'s number again"',
      "No last-visit date recorded anywhere in the household's records",
    ],
    confidence: 0.66,
    consideredAlternativeTypes: ["first_step_ambiguity"],
    isRediagnosis: false,
    supersededDiagnosisType: null,
    modelTier: "pro",
    promptVersion: "blocker-diagnosis-v3",
    invocationId: "inv-eye-checkup-diagnosis-1",
    diagnosedAt: "2026-08-18T12:00:00Z",
  };
}

/** Gate 9's "Information blocker -> fact fetched," resolved positively —
 * this obligation's information genuinely was the fetchable kind, which is
 * exactly what makes the later correction ("that was never the real
 * hold-up") legible as a correction, not a contradiction. */
export function getEyeCheckupInformationFetch(): InformationFetchResult {
  return {
    obligationId: TASK_EYE_CHECKUP_ID,
    missingFactDescription: "Dadi's last eye-exam date and Clearview Optics' phone number",
    fetched: true,
    factText:
      "Last eye exam: 14 March 2026 at Clearview Optics, Andheri, phone +91-80000-45678 (found in Dadi's medical documents).",
    confidence: 0.88,
    modelTier: "flash",
    promptVersion: "unblocker-information-fetch-v1",
    invocationId: "inv-eye-checkup-fetch-1",
  };
}

// ---------------------------------------------------------------------------
// Fixture — Aarav's school field-trip payment: Gate 9's "Decision blocker
// -> narrowed to binary."
// ---------------------------------------------------------------------------

export function getFieldTripDiagnosis(): BlockerDiagnosis {
  return {
    obligationId: TASK_FIELD_TRIP_PAYMENT_ID,
    personId: PRIYA_ID,
    blockerType: "decision",
    diagnosisText:
      "This is blocked because Priya hasn't decided whether to pay online or send cash with Aarav, the ₹450 fee itself was never in question, only the payment method.",
    evidence: [
      'School WhatsApp thread: "pay online via the parent portal, or send exact cash with your child by Friday"',
      "No portal payment recorded and no cash handed over, 6 days after the notice",
    ],
    confidence: 0.74,
    consideredAlternativeTypes: ["first_step_ambiguity"],
    isRediagnosis: false,
    supersededDiagnosisType: null,
    modelTier: "pro",
    promptVersion: "blocker-diagnosis-v3",
    invocationId: "inv-field-trip-diagnosis-1",
    diagnosedAt: "2026-08-19T08:00:00Z",
  };
}

export function getFieldTripDecisionNarrowing(): DecisionNarrowingResult {
  return {
    obligationId: TASK_FIELD_TRIP_PAYMENT_ID,
    optionA: "Pay ₹450 online via the school portal today, confirmation is instant.",
    optionB: "Send exact ₹450 cash with Aarav on Friday morning, no portal login needed.",
    framingText:
      "Both close this out before Friday's deadline; the real choice is whether Priya deals with the portal now or hands Aarav exact change Friday morning.",
    reasoning:
      "The school's own notice names exactly these two payment channels and no others, narrowing to them is not a guess, it's the full option set restated as a binary.",
    confidence: 0.8,
    modelTier: "pro",
    promptVersion: "unblocker-decision-narrowing-v1",
    invocationId: "inv-field-trip-narrowing-1",
  };
}

// ---------------------------------------------------------------------------
// Fixture — escorting Dadi to physiotherapy: Gate 9's own brief's fourth
// unblock outcome, a window blocker's real `AvailabilityVerdict`s. The
// person-availability half of every evaluation below is genuinely computed
// (`personAvailabilityForWindow`, `lib/schedule-availability.ts`) against a
// constraint set that mixes Dadi's one real, live `SCHEDULE` constraint
// with two fixture ones (see `getDadiPhysioConstraints`'s own doc comment)
// — never a hand-picked verdict label.
// ---------------------------------------------------------------------------

export function getDadiPhysioDiagnosis(): BlockerDiagnosis {
  return {
    obligationId: TASK_DADI_PHYSIO_ID,
    personId: DADI_ID,
    blockerType: "window",
    diagnosisText:
      "This is blocked because every proposed time lands inside one of Dadi's own real commitments, never because nobody is willing to take her.",
    evidence: [
      "Dadi's nap window (constraint-dadi-nap, daily 14:00-16:00, soft) has ruled out two prior proposed afternoon slots",
      "Dadi's cardiology follow-up (Tuesdays 09:00-11:00, hard) ruled out one proposed morning slot",
    ],
    confidence: 0.7,
    consideredAlternativeTypes: ["dependency"],
    isRediagnosis: false,
    supersededDiagnosisType: null,
    modelTier: "pro",
    promptVersion: "blocker-diagnosis-v3",
    invocationId: "inv-dadi-physio-diagnosis-1",
    diagnosedAt: "2026-08-21T09:00:00Z",
  };
}

/** A fixture `hard` cardiology commitment and a fixture legacy (pre-ADR-015)
 * entry, alongside Dadi's one real, live `SCHEDULE` constraint (passed in
 * separately by the caller from the live `/graph/snapshot`, keyed by
 * `DADI_NAP_CONSTRAINT_ID`) — added so this demo can honestly exercise
 * `hard_blocked` and `cannot_determine`, which no real constraint in the
 * live seed currently produces. Clearly fixture, documented as such here
 * and again in `WindowVerdictGallery`'s own UI copy. */
export function getDadiPhysioFixtureConstraints(): readonly ScheduleConstraintInput[] {
  return [
    {
      id: "constraint-fixture-dadi-cardiology",
      kind: "schedule",
      severity: "hard",
      structured: { days_of_week: "tue", start_time: "09:00", end_time: "11:00" },
    },
    {
      id: "constraint-fixture-dadi-legacy-quiet-hours",
      kind: "schedule",
      severity: "soft",
      // Deliberately pre-ADR-015 shape — exercises `cannot_determine`.
      structured: { quiet_hours: "20:00-22:00" },
    },
  ];
}

export interface WindowCandidateSpec {
  readonly window: readonly [string, string];
  readonly label: string;
}

/** Four candidate windows, one per real `AvailabilityVerdict` — Mon
 * afternoon (overlaps the real nap window), Tue morning (overlaps the
 * fixture hard cardiology slot), Wed evening (evaluated against only the
 * fixture legacy entry, to honestly demonstrate `cannot_determine` without
 * misattributing it to Dadi's real, already-migrated nap constraint), and
 * Thu late morning (clear of everything — the recommended slot). */
export function getDadiPhysioCandidates(): readonly WindowCandidateSpec[] {
  return [
    { window: ["2026-08-24T14:30:00Z", "2026-08-24T15:00:00Z"], label: "Mon 24 Aug, 2:30pm" },
    { window: ["2026-08-25T10:00:00Z", "2026-08-25T10:30:00Z"], label: "Tue 25 Aug, 10:00am" },
    { window: ["2026-08-26T20:30:00Z", "2026-08-26T21:00:00Z"], label: "Wed 26 Aug, 8:30pm" },
    { window: ["2026-08-27T11:00:00Z", "2026-08-27T11:30:00Z"], label: "Thu 27 Aug, 11:00am" },
  ];
}

/** Sunrise Physiotherapy's real-shaped, but fixture, counterparty verdict
 * and this household's historical-likelihood read for each of
 * `getDadiPhysioCandidates`'s four candidates, in the same order —
 * fixture-narrated deliberately (parsing a provider's free-text hours, or
 * reading household history, genuinely needs a model call per A25's own
 * design; only the person-availability half is real, deterministic
 * arithmetic this file can honestly compute itself). */
const DADI_PHYSIO_COUNTERPARTY_NARRATION: readonly {
  readonly counterpartyAvailability: CounterpartyAvailabilityVerdict | null;
  readonly historicalLikelihood: HistoricalLikelihoodVerdict;
  readonly reasoning: string;
}[] = [
  {
    counterpartyAvailability: "available",
    historicalLikelihood: "unlikely",
    reasoning:
      "Sunrise Physiotherapy is open then, but this slot falls inside Dadi's own real nap window, proposed twice before and never actually honoured.",
  },
  {
    counterpartyAvailability: null,
    historicalLikelihood: "insufficient_data",
    reasoning: "Dadi's own hard cardiology commitment rules this out before the clinic's hours are even relevant.",
  },
  {
    counterpartyAvailability: "unavailable",
    historicalLikelihood: "insufficient_data",
    reasoning:
      "Illustrative, evaluated only against a legacy, pre-ADR-015 schedule entry to demonstrate the honest 'cannot determine' verdict; Sunrise Physiotherapy is also closed at this hour.",
  },
  {
    counterpartyAvailability: "available",
    historicalLikelihood: "likely",
    reasoning:
      "Clear of every real and fixture constraint on file, the clinic is open, and late-morning slots are this household's most reliably honoured window.",
  },
];

/**
 * Builds the Dadi physio-escort demo's real `WindowFindingResult` — the
 * `personAvailability` half of every evaluation is genuinely computed
 * (`personAvailabilityForWindow`) against `realDadiNapConstraint` (the
 * live `constraint-dadi-nap`, when the caller found it in `/graph/
 * snapshot`) combined with `getDadiPhysioFixtureConstraints`'s two
 * fixture entries; the third candidate is deliberately evaluated against
 * only the fixture legacy entry (see `getDadiPhysioCandidates`'s own doc
 * comment) so `cannot_determine` is never misattributed to Dadi's real,
 * already-migrated constraint. `realDadiNapConstraint` may be `null` (the
 * live graph fetch failed, or the constraint was not found) — this
 * function degrades gracefully to the two fixture constraints alone
 * rather than crashing, never silently fabricating a substitute.
 */
export function buildDadiPhysioWindowResult(realDadiNapConstraint: ScheduleConstraintInput | null): WindowFindingResult {
  const fixtureConstraints = getDadiPhysioFixtureConstraints();
  const candidates = getDadiPhysioCandidates();
  const fullConstraintSet = realDadiNapConstraint ? [realDadiNapConstraint, ...fixtureConstraints] : fixtureConstraints;
  const legacyOnly = fixtureConstraints.filter((c) => c.id.includes("legacy"));

  const evaluations: WindowCandidateEvaluation[] = candidates.map((candidate, index) => {
    const narration = DADI_PHYSIO_COUNTERPARTY_NARRATION[index];
    // Candidate index 2 (Wed) is deliberately evaluated against the
    // legacy-only constraint set — see this function's own doc comment.
    const constraintsForThisCandidate = index === 2 ? legacyOnly : fullConstraintSet;
    const personAvailability = personAvailabilityForWindow(
      constraintsForThisCandidate,
      new Date(candidate.window[0]),
      new Date(candidate.window[1]),
    );
    const overallRecommended =
      personAvailability === "available" &&
      narration.counterpartyAvailability !== "unavailable" &&
      narration.counterpartyAvailability !== "cannot_determine";
    return {
      window: candidate.window,
      personAvailability,
      counterpartyAvailability: narration.counterpartyAvailability,
      historicalLikelihood: narration.historicalLikelihood,
      overallRecommended,
      reasoning: narration.reasoning,
    };
  });

  const recommended = evaluations.find((evaluation) => evaluation.overallRecommended) ?? null;

  return {
    obligationId: TASK_DADI_PHYSIO_ID,
    personId: DADI_ID,
    evaluations,
    bestWindow: recommended?.window ?? null,
    confidence: recommended ? 0.78 : 0.4,
    modelTier: "flash",
  };
}

// ---------------------------------------------------------------------------
// Fixture — Priya and Maya's friction profiles, before any correction this
// session. Aarav and Dadi start with no pattern on file at all (`Pattern`'s
// own contract: never fabricated from zero evidence) — `FrictionProfileView`
// renders that honestly as "no pattern on file yet," not an empty table.
// ---------------------------------------------------------------------------

export function getInitialFrictionPatterns(): readonly FrictionPattern[] {
  return [
    {
      id: "pattern-person-priya-aversion-v3",
      personId: PRIYA_ID,
      blockerType: "aversion",
      description:
        "Friction pattern (aversion), Priya: avoids calling unfamiliar clinics and businesses; confirmed across the pharmacy renewal, the society insurer, and the school-fee office calls (obligation obligation-renew-prescription)",
      supportCount: 3,
      confidence: patternConfidence(3),
      createdAt: "2026-07-30T10:00:00Z",
    },
    {
      id: "pattern-person-maya-window-v2",
      personId: MAYA_ID,
      blockerType: "window",
      description:
        "Friction pattern (window), Maya: daytime errands increasingly collide with sleep since starting night shifts; two of her last three attempted daytime tasks slipped past their window (obligation obligation-visit-pharmacy)",
      supportCount: 2,
      confidence: patternConfidence(2),
      createdAt: "2026-08-10T08:00:00Z",
    },
  ];
}
