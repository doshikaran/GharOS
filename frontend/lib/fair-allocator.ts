/**
 * TypeScript mirrors of the Phase 8 Fair Allocator's solver output and
 * agent output shapes (PHASES.md Phase 8, E4 work item — "cost matrix
 * visualisation... per-person fairness explanations").
 *
 * Source of truth, read directly rather than guessed at:
 *   - `backend/app/solvers/fair_allocation.py` — `AllocationPick`,
 *     `FairAllocationResult`, `EF1Violation`, `verify_ef1`,
 *     `solve_fair_allocation`, `OrphanedTaskError`.
 *   - `backend/app/agents/fair_allocator/types.py` — A17-A21's real output
 *     shapes: `ComparativePreference`, `ValuationExtractionResult`,
 *     `BundleComparison`, `PersonShareExplanation`,
 *     `FairnessVerificationResult`, `RenegotiationTrigger`,
 *     `ConcessionEvidence`, `LoadImbalanceFinding`.
 *   - `contracts/graph_types.py` — `ValuationProfile.elicitation_method`'s
 *     literal set, reused verbatim by `ValuationExtractionResult`.
 *
 * Field names are camelCase, following `lib/ledger.ts`'s established
 * fixture/wire-seam convention — every field maps 1:1 to its snake_case
 * Python name.
 *
 * **DATA-LOADING BOUNDARY (Phase 8's own brief, this file's documented
 * seam).** None of the five agents' output shapes above, nor the solver's
 * own `FairAllocationResult`/`EF1Violation`, have a REST endpoint this
 * phase — no role built one; Phase 8's backend work was agents + an
 * isolated solver, not a new API surface. Every `get*()` function below is
 * a fixture-backed seam, exactly the precedent `lib/ledger.ts` set in
 * Phase 7: realistic, richly-varied data typed exactly as the real backend
 * shape, so every consumer component depends only on the return type,
 * never the fixture body.
 *
 * **The one exception, per this phase's brief:** the cost matrix's raw
 * numbers for tasks the household has genuinely been asked about, and
 * every task's description, are real, live `/graph/snapshot` data — see
 * `lib/fair-allocator-matrix.ts`. The fixture data below is built to
 * *extend* that live data, never contradict it: Priya's real, live
 * `obligation-weekly-groceries` cost is `1.0` (`backend/seeds/
 * demo_household.py`'s `valuation1_priya`) and every fixture number below
 * that touches the same (person, task) pair uses that exact value — see
 * `PRIYA_LIVE_GROCERIES_COST` and this file's own test for the check.
 *
 * Continuous with `backend/seeds/demo_household.py` and Phase 7's ledger
 * fixtures — the same household (Priya, Aarav, Dadi, Maya) and the same
 * real node ids (`person-priya`, `person-maya`, `person-dadi`,
 * `person-aarav`, `obligation-renew-prescription`,
 * `obligation-visit-pharmacy`, `obligation-weekly-groceries`,
 * `obligation-pickup-aarav`, `obligation-pay-maya-salary`,
 * `obligation-pay-maintenance-v2`) — never a second, disconnected demo
 * family.
 *
 * ---------------------------------------------------------------------
 * HAND-CHECKABLE ARITHMETIC (matching `docs/FAIRNESS_GUARANTEE.md` §4's
 * own worked-example discipline — every number below was produced by
 * actually running `backend/app/solvers/fair_allocation.
 * solve_fair_allocation`/`verify_ef1` against the costs and feasibility
 * declared here, not picked to look plausible).
 *
 * This cycle's fair-allocation contest is scoped to the three flexible
 * errands both Priya and Maya are capability-eligible for — renewing
 * Dadi's prescription (`obligation-renew-prescription`), the pharmacy
 * pickup (`obligation-visit-pharmacy`), and the weekly grocery run
 * (`obligation-weekly-groceries`). The school pickup and Maya's own salary
 * payment go to Priya directly (she is the household's only driver and its
 * only bank-account holder); the extended maintenance payment goes to
 * Dadi directly (she and Priya are the household's only two signers, and
 * only Dadi has been asked to price it) — none of the three has a second
 * capability-eligible, priced person, so there is no contest to solve.
 *
 * BEFORE (this cycle's confirmed allocation):
 *   costs   = { priya: {o2: 7.0, o4: 6.0, o6: 1.0}, maya: {o2: 2.0, o4: 2.0, o6: 3.0} }
 *   order   = [maya, priya]  (lexicographic: "person-maya" < "person-priya")
 *   round 0: maya's cheapest is a tie {o2, o4} @ 2.0 -> "obligation-renew-prescription"
 *              sorts before "obligation-visit-pharmacy" -> maya takes o2 (2.0).
 *            priya's cheapest of {o4, o6} is o6 (1.0) -> priya takes o6 (1.0).
 *   round 1: maya's only remaining feasible task is o4 -> maya takes o4 (2.0).
 *   allocation = { o2: maya, o6: priya, o4: maya }
 *   personTotalCost = { maya: 4.0, priya: 1.0 }
 *   EF1: maya's own bundle costs her 4.0; removing her costliest item (2.0,
 *        either task) leaves 2.0, which is <= her own cost for priya's
 *        bundle (3.0) -> holds (real envy exists before the one-item
 *        removal: 4.0 > 3.0 -- resolved by it). priya's own bundle costs
 *        her 1.0, trivially <= her cost for maya's bundle (13.0) -> holds,
 *        no envy at all. verify_ef1 -> zero violations.
 *
 * AFTER (Maya starts night shifts -- her own cost for the two daytime
 * errands rises sharply; the grocery run, now on her route home from the
 * night shift, gets cheaper for her; Priya's own valuation is unchanged):
 *   costs.maya = {o2: 9.0, o4: 8.0, o6: 2.0}
 *   round 0: maya's cheapest is now o6 (2.0) -> maya takes o6 (2.0).
 *            priya's cheapest of {o2, o4} is o4 (6.0) -> priya takes o4 (6.0).
 *   round 1: maya's only remaining feasible task is o2 -> maya takes o2 (9.0).
 *   allocation = { o6: maya, o4: priya, o2: maya }
 *   personTotalCost = { maya: 11.0, priya: 6.0 }
 *   EF1: maya's own bundle costs her 11.0; removing her costliest item (9.0)
 *        leaves 2.0 <= her own cost for priya's bundle (8.0) -> holds.
 *        priya's own bundle costs her 6.0, trivially <= her cost for
 *        maya's bundle (1.0 + 7.0 = 8.0) -> holds. verify_ef1 -> zero
 *        violations, both before and after.
 *   Priya's own bundle cost went from 1.0 (before) to 6.0 (after) under her
 *   own unchanged valuation -- a real, computed concession (see
 *   `getConcessionEvidence`).
 * ---------------------------------------------------------------------
 */

// ---------------------------------------------------------------------------
// Solver output — `backend.app.solvers.fair_allocation`
// ---------------------------------------------------------------------------

export interface AllocationPick {
  readonly turnIndex: number;
  readonly roundNumber: number;
  readonly personId: string;
  readonly taskId: string;
  readonly cost: number;
}

export interface FairAllocationResult {
  /** task id -> person id. */
  readonly allocation: Readonly<Record<string, string>>;
  readonly picks: readonly AllocationPick[];
  /** person id -> total cost of their bundle, by their own valuation.
   * Present at `0.0` for a person who received nothing, mirroring the real
   * `FairAllocationResult.person_total_cost`'s own documented guarantee. */
  readonly personTotalCost: Readonly<Record<string, number>>;
  /** The fixed round-robin order actually used for this solve. */
  readonly order: readonly string[];
}

export interface EF1Violation {
  readonly envier: string;
  readonly envied: string;
  readonly envierOwnBundleCost: number;
  readonly envierCostForEnviedBundle: number;
  readonly envierWorstOwnItemCost: number;
}

// ---------------------------------------------------------------------------
// A17 — Interviewer output shape
// ---------------------------------------------------------------------------

export type ComparativePreferenceAnswer = "task_a" | "task_b" | "tie";

export interface ComparativePreference {
  readonly personId: string;
  readonly taskAId: string;
  readonly taskBId: string;
  readonly preferred: ComparativePreferenceAnswer;
  readonly rawAnswerText: string;
  readonly reasoning: string;
  readonly confidence: number;
}

// ---------------------------------------------------------------------------
// A18 — Valuation Extraction output shape
// ---------------------------------------------------------------------------

export type ElicitationMethod = "interview" | "complaint_inference" | "observed_history" | "mixed";

export interface ValuationExtractionResult {
  readonly valuationProfileId: string;
  readonly personId: string;
  /** Task id -> this person's real cost — sparse by omission, exactly
   * matching `ValuationProfile.costs`'s own contract. */
  readonly costs: Readonly<Record<string, number>>;
  readonly omittedTaskIds: readonly string[];
  readonly elicitationMethod: ElicitationMethod;
  /** Task id -> this model's real, per-task reasoning — never generic. */
  readonly reasoning: Readonly<Record<string, string>>;
  readonly confidence: number;
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
}

// ---------------------------------------------------------------------------
// A19 — Fairness Verifier / Explainer output shapes
// ---------------------------------------------------------------------------

export interface BundleComparison {
  readonly otherPersonId: string;
  readonly otherPersonTaskDescriptions: readonly string[];
  /** This envier's own cost for the other person's whole bundle. */
  readonly costToThisPerson: number;
}

export interface PersonShareExplanation {
  readonly personId: string;
  readonly taskIds: readonly string[];
  readonly totalCostToSelf: number;
  readonly explanationText: string;
  readonly confidence: number;
}

export interface FairnessVerificationResult {
  readonly ef1Holds: boolean;
  readonly violationCount: number;
  readonly explanations: readonly PersonShareExplanation[];
  readonly modelTier: "pro";
  readonly promptVersion: string;
  readonly invocationId: string;
}

// ---------------------------------------------------------------------------
// A20 — Renegotiation Trigger output shapes
// ---------------------------------------------------------------------------

export type RenegotiationReasonKind = "schedule_constraint_change" | "capability_change";

export interface RenegotiationTrigger {
  readonly triggerId: string;
  readonly personId: string;
  readonly reasonKind: RenegotiationReasonKind;
  readonly detail: string;
  /** ISO 8601. */
  readonly detectedAt: string;
  readonly confidence: number;
}

export interface ConcessionEvidence {
  readonly personId: string;
  readonly priorBundleCost: number;
  readonly newBundleCost: number;
  readonly reasoning: string;
}

// ---------------------------------------------------------------------------
// A21 — Load Monitor output shape
// ---------------------------------------------------------------------------

export type LoadImbalanceVerdict = "balanced" | "creeping_imbalance" | "insufficient_data";

export interface LoadImbalanceFinding {
  readonly personId: string;
  readonly expectedShare: number;
  readonly observedShare: number | null;
  readonly drift: number | null;
  readonly verdict: LoadImbalanceVerdict;
  readonly reasoning: string;
  readonly confidence: number;
  readonly modelTier: "flash" | "deterministic";
}

// ---------------------------------------------------------------------------
// Real node ids this fixture data is built on top of — never re-typed as
// magic strings at each call site (gharos-standards: no magic values).
// ---------------------------------------------------------------------------

export const PRIYA_ID = "person-priya";
export const MAYA_ID = "person-maya";
export const DADI_ID = "person-dadi";
export const AARAV_ID = "person-aarav";

export const TASK_RENEW_PRESCRIPTION_ID = "obligation-renew-prescription";
export const TASK_VISIT_PHARMACY_ID = "obligation-visit-pharmacy";
export const TASK_WEEKLY_GROCERIES_ID = "obligation-weekly-groceries";
export const TASK_PICKUP_AARAV_ID = "obligation-pickup-aarav";
export const TASK_PAY_MAYA_SALARY_ID = "obligation-pay-maya-salary";
export const TASK_PAY_MAINTENANCE_ID = "obligation-pay-maintenance-v2";

/** Priya's real, live `ValuationProfile.costs["obligation-weekly-
 * groceries"]` (`backend/seeds/demo_household.py`'s `valuation1_priya`) —
 * every fixture number touching this same (person, task) pair below must
 * equal this exactly; `fair-allocator.test.ts` asserts it. */
export const PRIYA_LIVE_GROCERIES_COST = 1.0;

// ---------------------------------------------------------------------------
// A17 fixture — the comparative answers behind this cycle's cost ordering
// ---------------------------------------------------------------------------

export function getComparativePreferences(): readonly ComparativePreference[] {
  return [
    {
      personId: MAYA_ID,
      taskAId: TASK_WEEKLY_GROCERIES_ID,
      taskBId: TASK_RENEW_PRESCRIPTION_ID,
      preferred: "task_b",
      rawAnswerText:
        "I'd rather call in the prescription than do the big grocery run, carrying all those bags back without a car takes forever.",
      reasoning: "Maya ranks the grocery run above both other flexible errands in effort.",
      confidence: 0.88,
    },
    {
      personId: MAYA_ID,
      taskAId: TASK_RENEW_PRESCRIPTION_ID,
      taskBId: TASK_VISIT_PHARMACY_ID,
      preferred: "tie",
      rawAnswerText: "Honestly those two feel about the same to me, quick errands either way.",
      reasoning: "Maya reports no meaningful difference between the two short errands.",
      confidence: 0.75,
    },
    {
      personId: PRIYA_ID,
      taskAId: TASK_WEEKLY_GROCERIES_ID,
      taskBId: TASK_RENEW_PRESCRIPTION_ID,
      preferred: "task_a",
      rawAnswerText:
        "I'd rather do the grocery run any day, I already have a routine for it. Calling the pharmacy always turns into sitting on hold forever.",
      reasoning: "Priya ranks the grocery run well below the prescription call in cost.",
      confidence: 0.9,
    },
    {
      personId: PRIYA_ID,
      taskAId: TASK_RENEW_PRESCRIPTION_ID,
      taskBId: TASK_VISIT_PHARMACY_ID,
      preferred: "task_b",
      rawAnswerText:
        "The pharmacy run is annoying but at least it's over quickly. The phone call for the renewal always turns into a whole thing.",
      reasoning: "Priya ranks the pharmacy visit below the prescription call in cost.",
      confidence: 0.82,
    },
  ];
}

// ---------------------------------------------------------------------------
// A18 fixture — the cost matrix used for this cycle's solve
// ---------------------------------------------------------------------------

export type AllocationScenario = "before" | "after";

export function getValuationExtractionResults(scenario: AllocationScenario): readonly ValuationExtractionResult[] {
  const priya: ValuationExtractionResult = {
    valuationProfileId: "valuation-priya-flexible-errands-cycle",
    personId: PRIYA_ID,
    costs: { [TASK_RENEW_PRESCRIPTION_ID]: 7.0, [TASK_VISIT_PHARMACY_ID]: 6.0 },
    omittedTaskIds: [],
    elicitationMethod: "interview",
    reasoning: {
      [TASK_RENEW_PRESCRIPTION_ID]:
        "Calling the pharmacy to renew the prescription means sitting on hold for a long time most days, priced above the pharmacy visit itself.",
      [TASK_VISIT_PHARMACY_ID]:
        "A dedicated trip to collect the prescription is a real errand out of the day, but at least it's quick once there, priced below the phone call.",
    },
    confidence: 0.8,
    modelTier: "pro",
    promptVersion: "fair-allocator-valuation-v1",
    invocationId: "inv-priya-flexible-errands-cycle",
  };

  const dadi: ValuationExtractionResult = {
    valuationProfileId: "valuation-dadi-maintenance",
    personId: DADI_ID,
    costs: { [TASK_PAY_MAINTENANCE_ID]: 4.0 },
    omittedTaskIds: [],
    elicitationMethod: "interview",
    reasoning: {
      [TASK_PAY_MAINTENANCE_ID]:
        "Dadi says signing the extended maintenance cheque is a quick, mildly tedious task, about as much effort as a routine errand.",
    },
    confidence: 0.8,
    modelTier: "pro",
    promptVersion: "fair-allocator-valuation-v1",
    invocationId: "inv-dadi-maintenance",
  };

  const mayaBefore: ValuationExtractionResult = {
    valuationProfileId: "valuation-maya-flexible-errands-cycle",
    personId: MAYA_ID,
    costs: { [TASK_RENEW_PRESCRIPTION_ID]: 2.0, [TASK_VISIT_PHARMACY_ID]: 2.0, [TASK_WEEKLY_GROCERIES_ID]: 3.0 },
    omittedTaskIds: [],
    elicitationMethod: "mixed",
    reasoning: {
      [TASK_RENEW_PRESCRIPTION_ID]: "A short phone call Maya can make from home between other tasks.",
      [TASK_VISIT_PHARMACY_ID]: "The pharmacy is two minutes' walk, barely an errand.",
      [TASK_WEEKLY_GROCERIES_ID]:
        "The weekly grocery run means carrying everything back without a car, the most physically demanding of the three.",
    },
    confidence: 0.85,
    modelTier: "pro",
    promptVersion: "fair-allocator-valuation-v1",
    invocationId: "inv-maya-flexible-errands-cycle-v1",
  };

  const mayaAfter: ValuationExtractionResult = {
    valuationProfileId: "valuation-maya-flexible-errands-cycle-v2",
    personId: MAYA_ID,
    costs: { [TASK_RENEW_PRESCRIPTION_ID]: 9.0, [TASK_VISIT_PHARMACY_ID]: 8.0, [TASK_WEEKLY_GROCERIES_ID]: 2.0 },
    omittedTaskIds: [],
    elicitationMethod: "interview",
    reasoning: {
      [TASK_RENEW_PRESCRIPTION_ID]:
        "Since starting the night shift Maya is asleep through the hours the pharmacy line is actually staffed, the call now means interrupting sleep to get through.",
      [TASK_VISIT_PHARMACY_ID]: "A daytime trip now cuts into the only real sleep window she has before the next shift.",
      [TASK_WEEKLY_GROCERIES_ID]:
        "She already passes the market on the walk home from the night shift, so the grocery run barely adds to her day anymore.",
    },
    confidence: 0.83,
    modelTier: "pro",
    promptVersion: "fair-allocator-valuation-v1",
    invocationId: "inv-maya-flexible-errands-cycle-v2",
  };

  return scenario === "before" ? [priya, dadi, mayaBefore] : [priya, dadi, mayaAfter];
}

// ---------------------------------------------------------------------------
// Solver fixture — see this file's "HAND-CHECKABLE ARITHMETIC" header
// comment for the full derivation of every number below.
// ---------------------------------------------------------------------------

export function getFairAllocationResult(scenario: AllocationScenario): FairAllocationResult {
  if (scenario === "before") {
    return {
      allocation: {
        [TASK_RENEW_PRESCRIPTION_ID]: MAYA_ID,
        [TASK_WEEKLY_GROCERIES_ID]: PRIYA_ID,
        [TASK_VISIT_PHARMACY_ID]: MAYA_ID,
      },
      picks: [
        { turnIndex: 0, roundNumber: 0, personId: MAYA_ID, taskId: TASK_RENEW_PRESCRIPTION_ID, cost: 2.0 },
        { turnIndex: 1, roundNumber: 0, personId: PRIYA_ID, taskId: TASK_WEEKLY_GROCERIES_ID, cost: PRIYA_LIVE_GROCERIES_COST },
        { turnIndex: 2, roundNumber: 1, personId: MAYA_ID, taskId: TASK_VISIT_PHARMACY_ID, cost: 2.0 },
      ],
      personTotalCost: { [MAYA_ID]: 4.0, [PRIYA_ID]: PRIYA_LIVE_GROCERIES_COST },
      order: [MAYA_ID, PRIYA_ID],
    };
  }
  return {
    allocation: {
      [TASK_WEEKLY_GROCERIES_ID]: MAYA_ID,
      [TASK_VISIT_PHARMACY_ID]: PRIYA_ID,
      [TASK_RENEW_PRESCRIPTION_ID]: MAYA_ID,
    },
    picks: [
      { turnIndex: 0, roundNumber: 0, personId: MAYA_ID, taskId: TASK_WEEKLY_GROCERIES_ID, cost: 2.0 },
      { turnIndex: 1, roundNumber: 0, personId: PRIYA_ID, taskId: TASK_VISIT_PHARMACY_ID, cost: 6.0 },
      { turnIndex: 2, roundNumber: 1, personId: MAYA_ID, taskId: TASK_RENEW_PRESCRIPTION_ID, cost: 9.0 },
    ],
    personTotalCost: { [MAYA_ID]: 11.0, [PRIYA_ID]: 6.0 },
    order: [MAYA_ID, PRIYA_ID],
  };
}

export function getEf1Violations(scenario: AllocationScenario): readonly EF1Violation[] {
  // Verified empty for both scenarios — see this file's header comment.
  // Parameter kept (rather than a single constant) so a future scenario
  // with a real violation has an obvious place to branch from.
  switch (scenario) {
    case "before":
    case "after":
      return [];
  }
}

// ---------------------------------------------------------------------------
// A19 fixture — verification + per-person explanations
// ---------------------------------------------------------------------------

export function getFairnessVerificationResult(scenario: AllocationScenario): FairnessVerificationResult {
  const violations = getEf1Violations(scenario);
  const explanations: readonly PersonShareExplanation[] =
    scenario === "before"
      ? [
          {
            personId: PRIYA_ID,
            taskIds: [TASK_WEEKLY_GROCERIES_ID],
            totalCostToSelf: PRIYA_LIVE_GROCERIES_COST,
            explanationText:
              "This cycle, your share is the weekly grocery run, 1.0 by your own stated cost, the cheapest of the three flexible errands to you. Maya's share (renewing Dadi's prescription and the pharmacy pickup) would cost you 13.0 if you took it on instead, so you have no reason to prefer her bundle to your own.",
            confidence: 0.88,
          },
          {
            personId: MAYA_ID,
            taskIds: [TASK_RENEW_PRESCRIPTION_ID, TASK_VISIT_PHARMACY_ID],
            totalCostToSelf: 4.0,
            explanationText:
              "This cycle, your share is renewing Dadi's prescription and the pharmacy pickup, 2.0 each, 4.0 total by your own stated cost. Priya's single grocery-run task would actually cost you only 3.0 if you'd taken it instead, so there is real envy here, but it is resolved by the envy-free-up-to-one-item guarantee: drop either one of your own two tasks (both cost you 2.0) and your remaining cost (2.0) is no more than what Priya's bundle would have cost you (3.0).",
            confidence: 0.85,
          },
        ]
      : [
          {
            personId: PRIYA_ID,
            taskIds: [TASK_VISIT_PHARMACY_ID],
            totalCostToSelf: 6.0,
            explanationText:
              "After this cycle's re-allocation, your share is the pharmacy pickup, 6.0 by your own stated cost, six times what your prior share (the grocery run, 1.0) cost you. You are absorbing this so the household can accommodate Maya's reduced daytime availability since she started night shifts.",
            confidence: 0.85,
          },
          {
            personId: MAYA_ID,
            taskIds: [TASK_WEEKLY_GROCERIES_ID, TASK_RENEW_PRESCRIPTION_ID],
            totalCostToSelf: 11.0,
            explanationText:
              "After this cycle's re-allocation, your share is the grocery run and renewing Dadi's prescription, 2.0 and 9.0, 11.0 total by your own current valuation. Priya's single pharmacy-pickup task would cost you 8.0 if you'd taken it instead, so there is real envy here too, resolved by dropping your own costliest task (the 9.0 prescription-renewal call): your remaining cost (2.0) is no more than what Priya's bundle would have cost you (8.0).",
            confidence: 0.8,
          },
        ];

  return {
    ef1Holds: violations.length === 0,
    violationCount: violations.length,
    explanations,
    modelTier: "pro",
    promptVersion: "fair-allocator-explainer-v1",
    invocationId: scenario === "before" ? "inv-explain-before" : "inv-explain-after",
  };
}

// ---------------------------------------------------------------------------
// A20 fixture — the renegotiation trigger and its concession evidence
// ---------------------------------------------------------------------------

export function getRenegotiationTrigger(): RenegotiationTrigger {
  return {
    triggerId: "trigger-maya-night-shift-2026-08",
    personId: MAYA_ID,
    reasonKind: "schedule_constraint_change",
    detail:
      "Maya started working night shifts three nights a week, sharply reducing her realistic daytime availability and raising her own cost for daytime errands.",
    detectedAt: "2026-08-25T22:00:00Z",
    confidence: 0.91,
  };
}

export function getConcessionEvidence(): readonly ConcessionEvidence[] {
  return [
    {
      personId: PRIYA_ID,
      priorBundleCost: PRIYA_LIVE_GROCERIES_COST,
      newBundleCost: 6.0,
      reasoning:
        "Priya's prior bundle (the grocery run) costs her 1.0 by her own current valuation; her new bundle (the pharmacy pickup) costs her 6.0 by that same, unchanged valuation, a real, computed 5.0 increase in her own burden, absorbed so the household could accommodate Maya's reduced daytime availability after starting night shifts.",
    },
  ];
}

// ---------------------------------------------------------------------------
// A21 fixture — load imbalance findings
//
// expectedShare derivation (this cycle's own numbers, plus the two other
// current obligations each assigned directly to their sole
// capability-eligible, priced person — see this file's header comment):
//   priya = (3.0 school pickup + 5.0 salary payment + 6.0 this cycle's
//            pharmacy-pickup share) / 29.0 total = 14/29 ~= 0.483
//   dadi  = 4.0 maintenance payment / 29.0 total              ~= 0.138
//   maya  = 11.0 this cycle's share (grocery run + prescription
//            renewal) / 29.0 total                            ~= 0.379
//   aarav = 0 / 29.0 total (no capability-eligible task this cycle) = 0.000
//   total = 14 + 4 + 11 + 0 = 29.0; 0.483 + 0.138 + 0.379 + 0.000 = 1.000
// ---------------------------------------------------------------------------

export function getLoadImbalanceFindings(): readonly LoadImbalanceFinding[] {
  return [
    {
      personId: PRIYA_ID,
      expectedShare: 0.483,
      observedShare: 0.55,
      drift: 0.067,
      verdict: "creeping_imbalance",
      reasoning:
        "Priya's current allocation assigns her about 48% of the household's total task cost, but she has completed roughly 55% of the household's actual observed obligation load over the past 30 days, she has repeatedly covered for Maya's night-shift-constrained availability beyond what this cycle's reallocation already accounted for.",
      confidence: 0.82,
      modelTier: "flash",
    },
    {
      personId: MAYA_ID,
      expectedShare: 0.379,
      observedShare: 0.3,
      drift: -0.079,
      verdict: "balanced",
      reasoning:
        "Maya's observed load is now below her expected share, consistent with the reduced daytime availability this cycle's reallocation already accounted for after she started night shifts, not flagged as a new imbalance.",
      confidence: 0.74,
      modelTier: "deterministic",
    },
    {
      personId: DADI_ID,
      expectedShare: 0.138,
      observedShare: 0.1,
      drift: -0.038,
      verdict: "balanced",
      reasoning:
        "Dadi's small expected share (the one recurring maintenance sign-off she handles) closely matches her observed load, no meaningful drift this window.",
      confidence: 0.88,
      modelTier: "deterministic",
    },
    {
      personId: AARAV_ID,
      expectedShare: 0.0,
      observedShare: 0.05,
      drift: 0.05,
      verdict: "balanced",
      reasoning:
        "Aarav has no capability-eligible task in the current obligation set, so his expected share is zero; his small observed load reflects occasional voluntary contributions (tidying his own room) outside the formal allocation cycle, not a drift worth flagging.",
      confidence: 0.7,
      modelTier: "deterministic",
    },
  ];
}
