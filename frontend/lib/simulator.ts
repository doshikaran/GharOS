/**
 * TypeScript mirrors of the Phase 11 Household Simulator's agent output
 * shapes (PHASES.md Phase 11, ADR-017, E4 work item — "branch comparison,
 * risk register, interrogation mode").
 *
 * Source of truth, read directly rather than guessed at:
 *   - ADR-017 ("Household Simulator") — the six agents (A35 Decision
 *     Framing, A36 Grounding/Research, A37 Path Simulator, A38 Consistency
 *     Critic, A39 Calibration, A40 Decision Synthesizer), the
 *     `MIN_SAMPLE_SIZE_FOR_CALIBRATION = 3` thin-history threshold, and
 *     backward mode as a second entry point on the same six agents rather
 *     than a seventh.
 *   - `contracts/graph_types.py` — `Decision` (`question`, `trigger`) and
 *     `Branch` (`label`, `projected_impacts`, `grounding_refs`,
 *     `critiques`), which `DecisionFrame`/`BranchProjection` below mirror.
 *   - The exact field names/shapes dispatched for this phase (E2 builds
 *     the Python originals against this same contract in parallel):
 *     `DecisionFrame`, `GroundedCitation`, `GroundingResult`,
 *     `BranchProjection`, `BranchCritique`, `DecisionBrief`,
 *     `BackwardModeAnalysis`.
 *
 * **DATA-LOADING BOUNDARY (documented seam, same convention as
 * `lib/approvals.ts` and `lib/fair-allocator.ts`).** No `/simulator`-style
 * backend endpoint exists yet — `backend/app/agents/simulator/` (A35-A40)
 * is E2's parallel Phase 11 work, not yet wired to a REST route. Every
 * `get*()` function below is a fixture-backed seam: it returns realistic,
 * internally-consistent data typed exactly as the real agents' output
 * shapes, so every component downstream depends only on the return type,
 * never the fixture body. Swapping a function body for a real fetch later
 * is a one-function change here, not a rewrite of any consumer.
 *
 * **On the citations below being "real-looking."** ADR-017 has A36 call
 * Gemini's genuine Vertex AI Google Search grounding tool in the backend —
 * real retrieved citations with real URIs, never a synthetic
 * citation-shaped fabrication (Gate 11: "pick any number in the brief and
 * demand its source"). The citations fixture-seeded here stand in for
 * that real call's shape (title, a real-looking resolvable URI, an ISO
 * `retrievedAt` timestamp) until A36 is wired to a live endpoint; they are
 * NOT asserted by this file to be live, verified sources today — exactly
 * the same honesty boundary every other fixture-backed lib file in this
 * app already documents.
 *
 * Continuous with `backend/seeds/demo_household.py` and every other
 * phase's fixtures — the same household (Priya, Aarav, Dadi) and the same
 * live R4 escalation already seeded in `lib/approvals.ts`
 * (`approval-redevelopment-buyback-brief`): Sunrise Apartments Society's
 * redevelopment buyback offer and the 90-day vacate deadline. This file's
 * `blastRadiusNodeIds` invent a small number of additional node ids in the
 * same naming convention (`person-*`, `obligation-*`, `constraint-*`,
 * `membership-*`) to illustrate decision-scale blast radius (Gate 11:
 * "board-exam year, dialysis schedule, non-transferring commitments") —
 * these are simulator-fixture ids, not a claim that
 * `backend/seeds/demo_household.py` already seeds them; E1's own Phase 11
 * blast-radius work item is a separate, backend-owned change.
 */

// ---------------------------------------------------------------------------
// DecisionFrame (A35 Decision Framing)
// ---------------------------------------------------------------------------

export interface DecisionFrame {
  readonly decisionId: string;
  readonly question: string;
  readonly trigger: string;
  readonly isFalseBinary: boolean;
  readonly unconsideredOptions: readonly string[];
  readonly proposedBranchLabels: readonly string[];
}

// ---------------------------------------------------------------------------
// GroundedCitation / GroundingResult (A36 Grounding/Research)
// ---------------------------------------------------------------------------

export interface GroundedCitation {
  readonly title: string;
  readonly uri: string;
  /** ISO 8601 — freshness of the *lookup*, never a claim about the
   * underlying page's own age (ADR-017). */
  readonly retrievedAt: string;
}

export interface GroundingResult {
  readonly branchLabel: string;
  readonly citations: readonly GroundedCitation[];
  readonly summary: string;
  readonly freshnessNote: string;
}

/** `en-IN`, matching `lib/approvals.ts:formatDateTime`'s convention — this
 * project's household is Indian Rupee / IST-oriented throughout. */
export function formatRetrievedAt(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(iso));
}

// ---------------------------------------------------------------------------
// BranchProjection (A37 Path Simulator) / BranchCritique (A38 Consistency
// Critic — critiques *another agent's* output, never its own)
// ---------------------------------------------------------------------------

export interface BranchProjection {
  readonly branchId: string;
  readonly label: string;
  readonly projectedImpacts: Readonly<Record<string, string>>;
  readonly groundingRefs: readonly string[];
  readonly blastRadiusNodeIds: readonly string[];
}

export interface BranchCritique {
  readonly branchId: string;
  readonly overOptimisticClaims: readonly string[];
  readonly omittedSecondOrderEffects: readonly string[];
  readonly revisedConfidenceNote: string;
}

// ---------------------------------------------------------------------------
// DecisionBrief (A40 Decision Synthesizer) — trade-offs, never a verdict.
// Deliberately no `recommendedBranchId` / verdict field anywhere on this
// type; see `lib/simulator.test.ts` for the standing assertion that no
// surface built from it ever states one either.
// ---------------------------------------------------------------------------

export interface DecisionBrief {
  readonly decisionId: string;
  readonly branchSummaries: readonly string[];
  readonly tradeOffs: readonly string[];
  readonly openQuestions: readonly string[];
}

// ---------------------------------------------------------------------------
// CalibrationEstimate (A39 Calibration) — not given verbatim in the phase
// brief's TypeScript block, but explicitly required by it ("Calibration
// panel: shows CalibrationEstimate-shaped data"). Shaped to match
// `backend/app/solvers/calibration_stats.py`'s described output (ADR-017
// Decision 1): a deterministic mean/variance/confidence-band computation
// over `Outcome.variance` floats sharing an `attribution_tags` category,
// with an explicit, named thin-history threshold below which no numeric
// confidence figure is produced — only the honest count and a plain
// statement (spec §11.5's "cold start... be honest").
// ---------------------------------------------------------------------------

/** Same threshold precedent as Phase 9's Slippage Analyst N=3 (ADR-017,
 * Decision 1) — a named constant, never a magic value scattered through
 * call sites. */
export const MIN_SAMPLE_SIZE_FOR_CALIBRATION = 3;

export interface CalibrationEstimate {
  /** The `Outcome.attribution_tags` category this estimate is over, e.g.
   * `"relocation"`, `"school_transition"`, `"staff_transition"`,
   * `"major_purchase"` (ADR-017's decision-category vocabulary). */
  readonly categoryTag: string;
  readonly sampleSize: number;
  /** `true` iff `sampleSize < MIN_SAMPLE_SIZE_FOR_CALIBRATION`. */
  readonly isThinHistory: boolean;
  /** Mean of past `Outcome.variance` for this category. `null` when thin —
   * never a manufactured number standing in for "not enough data." */
  readonly meanVariance: number | null;
  readonly stdevVariance: number | null;
  /** A plain-language confidence-band statement. `null` when thin. */
  readonly confidenceBandNote: string | null;
  /** Always present. States the thin-history case plainly when
   * `isThinHistory` is true; otherwise a short statement of what the
   * sample supports. Never fabricates precision either way. */
  readonly honestNote: string;
}

// ---------------------------------------------------------------------------
// BackwardModeAnalysis (A35 reframes, A39 supplies evidence, A40
// synthesizes — a second entry point on the same six agents, ADR-017
// Decision 3, never a seventh agent). Informational only: nothing here
// writes to Intention→Action automatically.
// ---------------------------------------------------------------------------

export interface BackwardModeAnalysis {
  readonly planDescription: string;
  readonly assumedFailurePoint: string;
  readonly supportingOutcomeIds: readonly string[];
  readonly confidenceNote: string;
  readonly suggestedMitigations: readonly string[];
}

// ---------------------------------------------------------------------------
// Fixture data — one decision, three branches. Continuous with the R4
// escalation already seeded in `lib/approvals.ts`
// (`approval-redevelopment-buyback-brief`): Sunrise Apartments Society's
// redevelopment buyback offer, a 90-day vacate deadline, a buyback price
// 12% under the last two independent valuations on file.
// ---------------------------------------------------------------------------

const DECISION_ID = "decision-redevelopment-relocation";

const DECISION_FRAME_FIXTURE: DecisionFrame = {
  decisionId: DECISION_ID,
  question:
    "Accept Sunrise Apartments Society's redevelopment buyback offer and relocate before the 90-day vacate deadline?",
  trigger:
    "Redevelopment notice sets a 90-day vacate deadline with a buyback price 12% under the last two independent valuations on file.",
  isFalseBinary: true,
  unconsideredOptions: [
    "Negotiate a rent-back extension with the developer that runs past the 90-day vacate deadline, buying time without forfeiting the buyback offer.",
    "Request a phased or partial relocation that keeps Dadi within her current dialysis centre's commute radius through the end of Aarav's board-exam year.",
  ],
  proposedBranchLabels: [
    "Accept and relocate immediately",
    "Reject and contest the valuation",
    "Accept, negotiate a 6-month rent-back",
  ],
} as const;

const BRANCH_IDS = {
  relocateNow: "branch-relocate-now",
  contestValuation: "branch-contest-valuation",
  rentBackExtension: "branch-rent-back-extension",
} as const;

const BRANCH_PROJECTIONS_FIXTURE: readonly BranchProjection[] = [
  {
    branchId: BRANCH_IDS.relocateNow,
    label: "Accept and relocate immediately",
    projectedImpacts: {
      finance: "Locks in the buyback price now, 12% under independent valuation, but avoids any forced-vacancy risk.",
      care: "Dadi's twice-weekly dialysis slot at Mehta Dialysis Centre must transfer to a new centre within the move window.",
      education: "Aarav's Class 10 board-exam year is mid-term at the relocation date, a school transfer would land during exam registration.",
      logistics: "Full packing and move must complete inside the 90-day window, concurrent with Diwali-season vendor availability.",
    },
    groundingRefs: ["cite-rera-buyback-norms", "cite-cbse-midyear-transfer"],
    blastRadiusNodeIds: [
      "person-dadi",
      "obligation-dadi-dialysis-schedule",
      "person-aarav",
      "constraint-aarav-board-exam-year",
      "membership-sunrise-society",
      "provider-mehta-dialysis-centre",
    ],
  },
  {
    branchId: BRANCH_IDS.contestValuation,
    label: "Reject and contest the valuation",
    projectedImpacts: {
      finance: "Preserves the possibility of a valuation closer to the two independent appraisals, but risks the buyback offer being withdrawn entirely.",
      care: "No disruption to Dadi's dialysis schedule while the dispute is unresolved.",
      education: "No disruption to Aarav's board-exam-year school placement.",
      logistics: "A formal valuation dispute with the society typically runs 60-120 days, may not resolve before the vacate deadline regardless.",
    },
    groundingRefs: ["cite-rera-buyback-norms", "cite-maharashtra-redevelopment-dispute-timeline"],
    blastRadiusNodeIds: [
      "membership-sunrise-society",
      "obligation-pay-maintenance-v2",
      "constraint-redevelopment-vacate-deadline",
    ],
  },
  {
    branchId: BRANCH_IDS.rentBackExtension,
    label: "Accept, negotiate a 6-month rent-back",
    projectedImpacts: {
      finance: "Same buyback price as immediate acceptance, plus a market-rate rent-back fee for the extension period.",
      care: "Dadi's dialysis transfer can be scheduled outside her twice-weekly slot, at a time the new centre confirms in writing.",
      education: "Aarav completes the current school term and sits his board exams before any transfer takes effect.",
      logistics: "Rent-back terms are not guaranteed, the developer may decline or price the extension high enough to erode the buyback's value.",
    },
    // No grounding refs: this branch's own grounding query returned zero
    // citations (see GROUNDING_RESULTS_FIXTURE below) — an honest empty
    // list, never a fabricated ref pointing at a source that isn't there
    // (ADR-017's "honest fallback, never fabricated" rule).
    groundingRefs: [],
    blastRadiusNodeIds: [
      "person-dadi",
      "obligation-dadi-dialysis-schedule",
      "person-aarav",
      "constraint-aarav-board-exam-year",
      "membership-sunrise-society",
    ],
  },
] as const;

const GROUNDING_RESULTS_FIXTURE: readonly GroundingResult[] = [
  {
    branchLabel: "Accept and relocate immediately",
    citations: [
      {
        title: "RERA guidance note: redevelopment buyback valuation norms",
        uri: "https://rera.gov.in/notices/redevelopment-buyback-valuation-norms",
        retrievedAt: "2026-08-26T05:12:00Z",
      },
      {
        title: "CBSE circular: mid-year transfer certificate and board-exam registration continuity",
        uri: "https://www.cbse.gov.in/cbsenew/circulars/mid-year-transfer-continuity.html",
        retrievedAt: "2026-08-26T05:14:00Z",
      },
    ],
    summary:
      "RERA's own guidance treats a buyback more than 10% under independent valuation as a flag worth raising with the society, not a settled figure. CBSE's circular confirms a mid-year transfer is permitted but requires the losing and receiving schools to jointly file a continuity form before board-exam registration closes.",
    freshnessNote:
      "Retrieved 2 days before this decision frame was assembled. Redevelopment timelines and society notices can change week to week, verify against the society's latest circular before acting on this branch.",
  },
  {
    branchLabel: "Reject and contest the valuation",
    citations: [
      {
        title: "RERA guidance note: redevelopment buyback valuation norms",
        uri: "https://rera.gov.in/notices/redevelopment-buyback-valuation-norms",
        retrievedAt: "2026-08-26T05:12:00Z",
      },
      {
        title: "Maharashtra redevelopment dispute resolution: typical timelines",
        uri: "https://mahasociety.gov.in/guidance/redevelopment-dispute-timelines",
        retrievedAt: "2026-08-26T05:16:00Z",
      },
    ],
    summary:
      "Dispute timelines documented by the state housing guidance page run 60-120 days on average, with no guarantee of resolution before a fixed vacate deadline, the dispute and the deadline run on independent clocks.",
    freshnessNote:
      "Retrieved 2 days before this decision frame was assembled. Dispute-resolution timelines are historical averages, not a promise about this specific case.",
  },
  {
    // Deliberately zero citations — the named honest-fallback failure mode
    // (ADR-017 Decision 2: "when Google Search grounding returns zero
    // chunks for a query... `GroundingResult.citations` is empty and A36's
    // summary states plainly that no external source was found, rather
    // than inventing one"). This is a real, expected outcome, not an error
    // state — see `BranchGroundingCitations`'s rendering of this case.
    branchLabel: "Accept, negotiate a 6-month rent-back",
    citations: [],
    summary:
      "No external source found for rent-back clause precedent with this developer or society. Google Search grounding returned zero relevant results for this query, stated plainly rather than inventing a citation to fill the gap.",
    freshnessNote:
      "Lookup attempted 2 days before this decision frame was assembled; it returned nothing to be fresh or stale, there is no source to date.",
  },
] as const;

const BRANCH_CRITIQUES_FIXTURE: readonly BranchCritique[] = [
  {
    branchId: BRANCH_IDS.relocateNow,
    overOptimisticClaims: [
      "Assumes a comparable dialysis slot will be available immediately at a new centre, Mehta Dialysis Centre's own transfer/waitlist process was never actually checked before this projection was written.",
      "Assumes the CBSE mid-year continuity form is a formality, it requires both schools' sign-off, and the receiving school has not been contacted.",
    ],
    omittedSecondOrderEffects: [
      "A rushed move during Diwali-season vendor scarcity risks paying a premium for movers, which is not reflected in the finance projection above.",
      "Aarav's peer group and exam-prep tuition arrangements are tied to the current school; a transfer disrupts both, not just the classroom seat.",
    ],
    revisedConfidenceNote:
      "Confidence in the finance projection stands; confidence in the care and education projections is revised down until the dialysis transfer and school continuity form are confirmed in writing.",
  },
  {
    branchId: BRANCH_IDS.contestValuation,
    overOptimisticClaims: [
      "Assumes the developer will hold the current buyback offer open indefinitely while a dispute plays out, nothing in the redevelopment notice guarantees that.",
    ],
    omittedSecondOrderEffects: [
      "A contested valuation with no signed agreement risks the developer proceeding to forced-vacancy proceedings, which historically settle at less favourable terms than the original offer.",
      "Maintaining obligation-pay-maintenance-v2 through a prolonged dispute keeps the household paying society dues for a flat it may still have to leave on worse terms.",
    ],
    revisedConfidenceNote:
      "Confidence in 'no disruption to Dadi or Aarav' holds only for as long as the dispute stays open, it is not a stable long-run outcome, and the projection above should not be read as one.",
  },
  {
    branchId: BRANCH_IDS.rentBackExtension,
    overOptimisticClaims: [
      "Assumes the developer will agree to a rent-back at all, no external source confirms this developer has offered one before, and the grounding search for this specific query returned nothing.",
    ],
    omittedSecondOrderEffects: [
      "If the developer declines the rent-back, the household is back to the immediate-relocation branch's timeline with less runway left before the vacate deadline, not a fresh 90 days.",
    ],
    revisedConfidenceNote:
      "This branch's own summary already flags a sourcing gap; treat the rent-back's very availability as unconfirmed, not merely its price.",
  },
] as const;

const DECISION_BRIEF_FIXTURE: DecisionBrief = {
  decisionId: DECISION_ID,
  branchSummaries: [
    "Accept and relocate immediately: fastest resolution and locks in the current buyback price, but the dialysis transfer and the board-exam-year school continuity are both unconfirmed, not guaranteed, commitments.",
    "Reject and contest the valuation: protects Dadi's and Aarav's continuity while the dispute is open, but risks the buyback offer being withdrawn and provides no guarantee the dispute resolves before the vacate deadline.",
    "Accept, negotiate a 6-month rent-back: preserves the buyback price and lets Aarav finish his exam term, but the rent-back itself is unconfirmed, no source establishes this developer offers one.",
  ],
  tradeOffs: [
    "Speed of resolution versus continuity of Dadi's dialysis care and Aarav's board-exam term.",
    "Preserving the buyback price versus the legal and relationship cost of formally contesting it.",
    "Certainty of an agreed timeline versus a rent-back extension that depends on the developer's willingness to grant one.",
  ],
  openQuestions: [
    "Would Mehta Dialysis Centre, or a partner centre near the new location, confirm a transferred slot in writing before any move is committed to?",
    "Does CBSE's mid-year continuity process, once actually filed with both schools, complete before board-exam registration closes?",
    "Has this developer granted a rent-back extension to any other unit in this redevelopment, and on what terms?",
  ],
} as const;

// ---------------------------------------------------------------------------
// CalibrationEstimate fixtures — two distinct rendering paths, both real
// failure/success modes named by ADR-017 and Gate 11 ("Calibration uses
// real variance; thin history acknowledged").
// ---------------------------------------------------------------------------

const RELOCATION_CALIBRATION_FIXTURE: CalibrationEstimate = {
  categoryTag: "relocation",
  sampleSize: 2,
  isThinHistory: true,
  meanVariance: null,
  stdevVariance: null,
  confidenceBandNote: null,
  honestNote:
    "Only 2 prior relocation-category outcomes exist in this household's history, below the minimum of 3 needed for a reliable variance estimate. Stated plainly rather than manufacturing a confidence figure the data doesn't support.",
} as const;

const STAFF_TRANSITION_CALIBRATION_FIXTURE: CalibrationEstimate = {
  categoryTag: "staff_transition",
  sampleSize: 5,
  isThinHistory: false,
  meanVariance: 0.18,
  stdevVariance: 0.05,
  confidenceBandNote: "68% confidence band: 0.13-0.23 (mean ± 1 stdev, n=5).",
  honestNote:
    "5 prior staff-transition outcomes on file, enough to support the variance figures above, though still a small sample; treat the confidence band as indicative, not a precise guarantee.",
} as const;

const CALIBRATION_ESTIMATES_BY_CATEGORY: Readonly<Record<string, CalibrationEstimate>> = {
  relocation: RELOCATION_CALIBRATION_FIXTURE,
  staff_transition: STAFF_TRANSITION_CALIBRATION_FIXTURE,
};

// ---------------------------------------------------------------------------
// BackwardModeAnalysis fixture — same decision, reframed backward
// (ADR-017 Decision 3: A35 reframes, A39 supplies OUTCOME-variance
// evidence, A40 narrates — same six agents, a second entry point).
// ---------------------------------------------------------------------------

const BACKWARD_MODE_ANALYSIS_FIXTURE: BackwardModeAnalysis = {
  planDescription:
    "Committed plan: accept Sunrise Apartments Society's buyback offer and relocate the household within the 90-day vacate window.",
  assumedFailurePoint:
    "Assume this failed: six months after the move, Dadi's dialysis care lapsed for at least one week during the centre transfer, and Aarav's board-exam continuity form was filed too late to count toward his registration.",
  supportingOutcomeIds: ["outcome-staff-transition-maya-2025", "outcome-relocation-2019-vacate"],
  confidenceNote:
    "Based on only 2 prior household relocation-category outcomes (thin history, see the Calibration panel), this is a plausible failure mode worth planning around, not a statistically confident prediction.",
  suggestedMitigations: [
    "Confirm a transferred dialysis slot for Dadi in writing at the new location before signing the buyback agreement, not after.",
    "File the CBSE mid-year continuity form for Aarav jointly with both schools before committing to any move date inside the exam-registration window.",
    "Ask the society or developer for a written moving-logistics allowance given the Diwali-season timing, rather than absorbing a premium unbudgeted.",
  ],
} as const;

// ---------------------------------------------------------------------------
// Accessors — every consumer depends on these return types, never the
// fixture bodies above (see this file's DATA-LOADING BOUNDARY comment).
// ---------------------------------------------------------------------------

export function getDecisionFrame(): DecisionFrame {
  return DECISION_FRAME_FIXTURE;
}

export function getBranchProjections(): readonly BranchProjection[] {
  return BRANCH_PROJECTIONS_FIXTURE;
}

export function getGroundingResults(): readonly GroundingResult[] {
  return GROUNDING_RESULTS_FIXTURE;
}

export function getBranchCritiques(): readonly BranchCritique[] {
  return BRANCH_CRITIQUES_FIXTURE;
}

export function getDecisionBrief(): DecisionBrief {
  return DECISION_BRIEF_FIXTURE;
}

export function getCalibrationEstimate(categoryTag: string): CalibrationEstimate | undefined {
  return CALIBRATION_ESTIMATES_BY_CATEGORY[categoryTag];
}

export function getBackwardModeAnalysis(): BackwardModeAnalysis {
  return BACKWARD_MODE_ANALYSIS_FIXTURE;
}

// ---------------------------------------------------------------------------
// Risk register — derived by flattening every branch's critique into a
// flat, scannable list (this phase's brief: "risk register: derived from
// the critiques across all branches"). A pure function over the critique
// fixture, not a stored/duplicated list, so it can never drift from the
// per-branch critiques rendered in the branch comparison above it.
// ---------------------------------------------------------------------------

export type RiskCategory = "over-optimistic claim" | "omitted second-order effect";

export interface RiskRegisterEntry {
  readonly branchId: string;
  readonly branchLabel: string;
  readonly category: RiskCategory;
  readonly text: string;
}

/**
 * Flattens every `BranchCritique` in `critiques` into one flat list, each
 * entry naming the branch and category it came from — a household member
 * scanning this list should never have to cross-reference back to a
 * specific branch card to know what a risk is about. `branchLabel` is
 * resolved from `projections`; a critique whose `branchId` has no matching
 * projection is skipped rather than rendered with a dangling label
 * (defensive, since this is genuinely two independently-produced agent
 * outputs being joined at render time).
 */
export function buildRiskRegister(
  critiques: readonly BranchCritique[],
  projections: readonly BranchProjection[],
): readonly RiskRegisterEntry[] {
  const labelById = new Map(projections.map((projection) => [projection.branchId, projection.label]));
  const entries: RiskRegisterEntry[] = [];

  for (const critique of critiques) {
    const branchLabel = labelById.get(critique.branchId);
    if (branchLabel === undefined) continue;

    for (const claim of critique.overOptimisticClaims) {
      entries.push({ branchId: critique.branchId, branchLabel, category: "over-optimistic claim", text: claim });
    }
    for (const effect of critique.omittedSecondOrderEffects) {
      entries.push({
        branchId: critique.branchId,
        branchLabel,
        category: "omitted second-order effect",
        text: effect,
      });
    }
  }

  return entries;
}

// ---------------------------------------------------------------------------
// Interrogation mode — "what if...?" against a `DecisionBrief`. A stubbed,
// fixture-backed client function (this phase's brief: "a simple
// question-input + answer-list UI ... calling a stubbed
// `answerFollowup(brief, question)` client function"), same seam
// convention as every other fixture-backed surface in this app. Real
// question-answering against the graph/A40 is out of scope this phase —
// this is a deterministic keyword match over the brief's own trade-offs
// and open questions, never inventing an answer the brief doesn't support,
// and never stating a verdict.
// ---------------------------------------------------------------------------

const FALLBACK_ANSWER =
  "This isn't something the Simulator answers with a single figure. See the branch comparison and risk register above for what's known and what remains genuinely open, ask about a specific trade-off or open question for a more direct pointer.";

/**
 * Deterministic, fixture-backed stand-in for a real follow-up-question
 * agent call. Matches `question` against `brief.tradeOffs` and
 * `brief.openQuestions` by simple keyword overlap and returns the closest
 * match verbatim, prefixed to say which it found; returns
 * `FALLBACK_ANSWER` when nothing matches closely enough. Never returns a
 * recommendation or verdict — it can only ever surface something already
 * present in `brief`, which itself carries no verdict field.
 */
/** Common words long enough to pass the length filter but carrying no
 * topical signal — excluded so two unrelated sentences that both happen to
 * contain "what" or "have" don't register as a match. */
const STOPWORDS = new Set([
  "what",
  "when",
  "where",
  "which",
  "does",
  "have",
  "with",
  "this",
  "that",
  "from",
  "been",
  "were",
  "will",
  "your",
  "about",
  "would",
  "could",
  "should",
  "than",
  "then",
  "them",
  "their",
]);

function significantWords(text: string): string[] {
  return text
    .toLowerCase()
    .split(/\W+/)
    .filter((word) => word.length > 3 && !STOPWORDS.has(word));
}

export function answerFollowup(brief: DecisionBrief, question: string): string {
  const questionWords = new Set(significantWords(question));

  function bestMatch(candidates: readonly string[]): { text: string; score: number } | null {
    let best: { text: string; score: number } | null = null;
    for (const candidate of candidates) {
      const candidateWords = significantWords(candidate);
      const score = candidateWords.filter((word) => questionWords.has(word)).length;
      if (score > 0 && (best === null || score > best.score)) {
        best = { text: candidate, score };
      }
    }
    return best;
  }

  const tradeOffMatch = bestMatch(brief.tradeOffs);
  const openQuestionMatch = bestMatch(brief.openQuestions);

  if (openQuestionMatch && (!tradeOffMatch || openQuestionMatch.score >= tradeOffMatch.score)) {
    return `Already an open question on this brief: "${openQuestionMatch.text}" It isn't answered yet, that's exactly why it's listed as open, not resolved by guessing.`;
  }

  if (tradeOffMatch) {
    return `The relevant trade-off on this brief: "${tradeOffMatch.text}" Both sides of that trade-off are stated above; the brief does not weigh one as better than the other.`;
  }

  return FALLBACK_ANSWER;
}
