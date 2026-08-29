/**
 * TypeScript mirror of the Phase 12 Household Council's agent output
 * shapes (PHASES.md Phase 12, ADR-019, E4 work item — "Council view:
 * positions with evidence, explicit trade-off, permanent record").
 *
 * Source of truth, read directly rather than guessed at:
 *   - `GharOS_Build_Spec_v2.md` §12.2-§12.5 — the critical distinction
 *     (specialists differ in information and interest, never opinion;
 *     positions are reported, never averaged; resolution is computed by
 *     deterministic code) and the car/house worked examples this fixture
 *     is grounded in.
 *   - ADR-019 Decision 1 (`ScopedGraphReader`, five disjoint specialist
 *     subgraph scopes), Decision 3 (minimax-regret arbiter with leximin
 *     refinement, Savage 1951 — never a utilitarian sum or Nash welfare,
 *     since costs are only ever comparable *within* one person's own
 *     matrix, never across people), Decision 4 (decision-scoped
 *     `ValuationProfile`s, never a reuse of chore-era cost values), and
 *     Decision 7 (the Adversary attacks the arbiter's own winning branch —
 *     there is no separate, earlier "leading option").
 *   - The exact field names/shapes given for this phase (E2 builds the
 *     Python originals against this same contract in parallel):
 *     `CouncilComposition`, `SpecialistPosition`, `DelegateScoring`,
 *     `AdversaryAttack`, `CouncilResolution`, `CouncilBrief`.
 *
 * **THE WORD THIS FILE NEVER USES.** Spec §12.2 / safety invariant 6 /
 * Gate 12: the Council is agents differing in information and interest,
 * never multi-agent "debate" — that word appears nowhere in this file, any
 * component under `components/council/`, or their rendered output
 * (`components/council/__tests__` and this file's own test enforce it by
 * grep, not by promise).
 *
 * **DATA-LOADING BOUNDARY (documented seam, same convention as
 * `lib/simulator.ts` and `lib/fair-allocator.ts`).** No `/council`-style
 * backend endpoint exists yet — `backend/app/agents/council/` (A41-A49) is
 * E2's parallel Phase 12 work, not yet wired to a REST route. Every
 * `get*()` function below is a fixture-backed seam: it returns realistic,
 * internally-consistent data typed exactly as the real agents' output
 * shapes, so every component downstream depends only on the return type,
 * never the fixture body. Swapping a function body for a real fetch later
 * is a one-function change here, not a rewrite of any consumer. The
 * historical decision browser (`lib/council-history.ts`) is the one part
 * of this phase that is *not* fixture-backed — ADR-019's own closing note
 * is that it needs no new endpoint at all, since `/graph/snapshot`
 * (already fetched by `lib/graph-api.ts`) already carries every
 * `Decision`/`Branch`/`CouncilPosition` node and `CONCEDED_BY` edge
 * generically.
 *
 * Continuous with `backend/seeds/demo_household.py` and every other
 * phase's fixtures — the same household (Priya, Aarav, Dadi, Maya) and
 * real node ids reused verbatim from `lib/fair-allocator.ts`
 * (`PRIYA_ID`/`MAYA_ID`/`DADI_ID`) and `lib/simulator.ts`
 * (`obligation-dadi-dialysis-schedule`, the outcome id
 * `outcome-relocation-2019-vacate`). Per ADR-019 Decision 4, the *type*
 * (`ElicitationMethod`) is reused from `lib/fair-allocator.ts`, but every
 * cost value below is a fresh, decision-scoped number for this car
 * decision — never a chore-era valuation reused across decisions.
 */

import { AARAV_ID, DADI_ID, MAYA_ID, PRIYA_ID, type ElicitationMethod } from "./fair-allocator";

// ---------------------------------------------------------------------------
// Wire shapes (A41 Convener / A42-A46 Specialists / A47 Delegates /
// A48 Adversary / the deterministic arbiter / A49 Recorder's brief)
// ---------------------------------------------------------------------------

export interface CouncilComposition {
  readonly decisionId: string;
  readonly question: string;
  readonly trigger: string;
  readonly convenedSpecialistIds: readonly string[];
  readonly convenedDelegatePersonIds: readonly string[];
}

export type CouncilStance = "supports" | "opposes" | "neutral";

export interface SpecialistPosition {
  readonly agentId: string;
  readonly stance: CouncilStance;
  readonly reasoning: string;
  readonly evidenceRefs: readonly string[];
  readonly eliminatedBranchIds: readonly string[];
}

export interface CouncilValuationProfile {
  readonly personId: string;
  readonly costs: Readonly<Record<string, number>>;
  readonly elicitationMethod: ElicitationMethod;
}

export interface DelegateScoring {
  readonly personId: string;
  readonly valuationProfile: CouncilValuationProfile;
  readonly reasoning: string;
}

export interface AdversaryAttack {
  readonly targetBranchId: string;
  readonly critique: string;
  readonly citedOutcomeIds: readonly string[];
}

export interface CouncilResolution {
  readonly winningBranchId: string;
  readonly regretByPerson: Readonly<Record<string, number>>;
  readonly mostCostlyTo: string | null;
  readonly mostFavorableTo: string | null;
  readonly concedingPersonIds: readonly string[];
  readonly eliminatedBranchIds: readonly string[];
}

export interface CouncilBrief {
  readonly decisionId: string;
  readonly question: string;
  readonly specialistPositions: readonly SpecialistPosition[];
  readonly delegateScorings: readonly DelegateScoring[];
  readonly adversaryAttack: AdversaryAttack;
  readonly resolution: CouncilResolution;
  readonly riskRegister: readonly string[];
}

// ---------------------------------------------------------------------------
// Specialist / branch identity — display-only lookups. Not part of the
// wire contract; these live here because every consumer component needs
// the same mapping and it must never drift between them.
// ---------------------------------------------------------------------------

/** A41-A46 agent ids convened for this decision, each named with the
 * subgraph it queries (ADR-019 Decision 1's five disjoint scopes) — this
 * is the concrete, on-screen evidence that no two specialists share tool
 * access, not just an assertion. */
export const AGENT_DOMAIN_LABEL: Readonly<Record<string, string>> = {
  A42: "Finance: Ledger subgraph",
  A43: "Care: Constraint subgraph (medical / mobility)",
  A44: "Education: Constraint subgraph (education)",
  A45: "Logistics: Obligation subgraph",
  A46: "Legal / Compliance: Documentation subgraph",
};

export const AGENT_SHORT_LABEL: Readonly<Record<string, string>> = {
  A42: "Finance",
  A43: "Care",
  A44: "Education",
  A45: "Logistics",
  A46: "Legal / Compliance",
};

export const PERSON_LABELS: Readonly<Record<string, string>> = {
  [PRIYA_ID]: "Priya",
  [MAYA_ID]: "Maya",
  [DADI_ID]: "Dadi",
  [AARAV_ID]: "Aarav",
};

export function agentDomainLabel(agentId: string): string {
  return AGENT_DOMAIN_LABEL[agentId] ?? agentId;
}

export function agentShortLabel(agentId: string): string {
  return AGENT_SHORT_LABEL[agentId] ?? agentId;
}

export function personLabel(personId: string): string {
  return PERSON_LABELS[personId] ?? personId;
}

export const BRANCH_LABELS: Readonly<Record<string, string>> = {
  "branch-compact-hatchback": "Compact hatchback (current shortlist leader on price)",
  "branch-compact-suv": "Compact SUV",
  "branch-sedan": "Mid-size sedan",
};

export function branchLabel(branchId: string): string {
  return BRANCH_LABELS[branchId] ?? branchId;
}

/**
 * Given every specialist position, finds which specialist eliminated a
 * given branch — the historical-record answer to "who ruled this out and
 * why," never left as an unattributed fact (this phase's brief: "an
 * eliminated branch renders as removed from consideration... with the
 * eliminating specialist named").
 */
export function eliminatingAgentForBranch(
  positions: readonly SpecialistPosition[],
  branchId: string,
): string | undefined {
  return positions.find((position) => position.eliminatedBranchIds.includes(branchId))?.agentId;
}

// ---------------------------------------------------------------------------
// Fixture data — one decision, grounded in spec §12.4's own car worked
// example, adapted to this household's real, already-seeded members
// (Priya, Maya, Dadi have real ValuationProfiles in `lib/fair-allocator.ts`;
// there is no second adult in this household's real seed, so "delegates
// for both adults and one for the elder" reads as Priya + Maya (adults)
// and Dadi (elder) rather than inventing an unseeded person).
//
// HAND-CHECKABLE ARITHMETIC (same discipline as `lib/fair-allocator.ts`'s
// own worked example): the regret figures below were computed, not picked
// to look plausible — see `computeRegretByPerson` and this file's test for
// the reproduction. Costs are within-person-only comparable (ADR-019
// Decision 3): a lower number is better *for that person*, never compared
// in magnitude across people.
//
// costs   = { priya: {suv: 3.0, sedan: 5.0}, maya: {suv: 6.0, sedan: 3.0},
//             dadi:  {suv: 1.0, sedan: 8.0} }
// regret_i(o) = cost_i(o) - min(cost_i(o') for surviving o')
//   priya: min=3.0(suv) -> regret(suv)=0,   regret(sedan)=2.0
//   maya:  min=3.0(sedan)-> regret(suv)=3.0, regret(sedan)=0
//   dadi:  min=1.0(suv) -> regret(suv)=0,   regret(sedan)=7.0
// max_i regret(suv)   = max(0, 3.0, 0) = 3.0
// max_i regret(sedan) = max(2.0, 0, 7.0) = 7.0
// minimax winner = suv (3.0 < 7.0) — no leximin tie, no final lexical
// tiebreak needed.
// ---------------------------------------------------------------------------

const DECISION_ID = "decision-buy-car";

const BRANCH_IDS = {
  hatchback: "branch-compact-hatchback",
  suv: "branch-compact-suv",
  sedan: "branch-sedan",
} as const;

const COUNCIL_COMPOSITION_FIXTURE: CouncilComposition = {
  decisionId: DECISION_ID,
  question: "Replace the household car, or keep paying for repairs on the current one?",
  trigger:
    "Three maintenance ledger events on the current car in three months (₹8,200 in June, ₹11,400 in July, ₹14,900 in August, a rising trend), plus Priya's stated intention captured in a message: \"this car needs to go, it's bleeding us.\"",
  convenedSpecialistIds: ["A42", "A43", "A45"],
  convenedDelegatePersonIds: [PRIYA_ID, MAYA_ID, DADI_ID],
} as const;

const SPECIALIST_POSITIONS_FIXTURE: readonly SpecialistPosition[] = [
  {
    agentId: "A42",
    stance: "neutral",
    reasoning:
      "Three repair debits this year total ₹34,500 against a car bought for ₹2.1L five years ago. After existing recurring commitments, society maintenance, Maya's salary, weekly groceries, and given Aarav's board-exam-year school fees due in March, the household's real EMI headroom supports a maximum instalment of ₹9,000/month over 60 months. That is a computed affordability band from real ledger history, not a guess at what the household can 'probably' afford.",
    evidenceRefs: [
      "ledger-car-repair-jun",
      "ledger-car-repair-jul",
      "ledger-car-repair-aug",
      "obligation-pay-maintenance-v2",
      "obligation-pay-maya-salary",
    ],
    eliminatedBranchIds: [],
  },
  {
    agentId: "A43",
    stance: "opposes",
    reasoning:
      "Dadi's mobility constraint sets a minimum door-sill height and a maximum seat-to-ground height compatible with a standing transfer, not a seated slide-in, she cannot get into a low-slung cabin unassisted. The compact hatchback on the household's shortlist has a 36cm door-sill height and low bucket seats; it fails both thresholds. This is a hard constraint: the hatchback is removed from consideration, not scored down against the other options.",
    evidenceRefs: ["constraint-dadi-mobility"],
    eliminatedBranchIds: [BRANCH_IDS.hatchback],
  },
  {
    agentId: "A45",
    stance: "supports",
    reasoning:
      "The car carries Aarav's school pickup five days a week, Dadi's dialysis transport twice a week, and the monthly grocery run, real recurring obligations, not hypothetical trips. Boot space needs to hold a folded wheelchair alongside the weekly grocery haul, and Sunrise Society's allotted parking bay is a fixed 4.3m, both surviving options fit; the compact SUV's higher ground clearance also copes better with the society's speed-bump-heavy internal road, which the current car has scraped against twice this year.",
    evidenceRefs: ["obligation-pickup-aarav", "obligation-dadi-dialysis-schedule", "obligation-weekly-groceries"],
    eliminatedBranchIds: [],
  },
] as const;

const DELEGATE_SCORINGS_FIXTURE: readonly DelegateScoring[] = [
  {
    personId: PRIYA_ID,
    valuationProfile: {
      personId: PRIYA_ID,
      costs: { [BRANCH_IDS.suv]: 3.0, [BRANCH_IDS.sedan]: 5.0 },
      elicitationMethod: "interview",
    },
    reasoning:
      "Priya drives every leg herself. She rated the compact SUV's easier reverse-park into Sunrise Society's tight bay well ahead of the sedan's longer rear overhang, which has already meant two failed parking attempts with the current car.",
  },
  {
    personId: MAYA_ID,
    valuationProfile: {
      personId: MAYA_ID,
      costs: { [BRANCH_IDS.suv]: 6.0, [BRANCH_IDS.sedan]: 3.0 },
      elicitationMethod: "interview",
    },
    reasoning:
      "Maya loads and unloads the weekly grocery haul and pharmacy deliveries alone. She rated the sedan's low boot lip well ahead of the SUV's higher liftover, which she flagged as a real strain on her back on the observed heavier grocery weeks.",
  },
  {
    personId: DADI_ID,
    valuationProfile: {
      personId: DADI_ID,
      costs: { [BRANCH_IDS.suv]: 1.0, [BRANCH_IDS.sedan]: 8.0 },
      elicitationMethod: "observed_history",
    },
    reasoning:
      "Dadi's own transfers in and out of the current car were observed and timed across her twice-weekly dialysis trips. The compact SUV's higher seat height needs no assisted lift; the sedan's low seat has, on the current car, taken her upward of a minute and a hand from Priya every time.",
  },
] as const;

const ADVERSARY_ATTACK_FIXTURE: AdversaryAttack = {
  targetBranchId: BRANCH_IDS.suv,
  critique:
    "This household has underestimated maintenance cost before, the same optimism gap that triggered this very council. The compact SUV's authorised service network in this city is thin: only two centres, both over 12km away, versus five for the sedan. A thin service network is exactly the kind of gap that turned three routine repairs into ₹34,500 on the outgoing car; nothing in the affordability band above prices in a repeat of that pattern on a new vehicle.",
  citedOutcomeIds: ["outcome-car-amc-underestimate-2022", "outcome-relocation-2019-vacate"],
} as const;

/**
 * Regret of one surviving `branchId` for every delegate, keyed by
 * personId — `regret_i(o) = cost_i(o) - min(cost_i(o') for o' in
 * survivingBranchIds)` (ADR-019 Decision 3, Savage 1951, minimax regret).
 * This is **not** a re-implementation of the real arbiter
 * (`backend/app/solvers/council_arbiter.py`, E1's own pure function) — it
 * exists solely so this fixture file's own test can prove the
 * `CouncilResolution` fixture below is arithmetically honest, picking the
 * branch that actually minimises the maximum regret, rather than
 * hand-typed and hopeful — the same discipline `lib/fair-allocator.ts`
 * applies to its own EF1 worked example.
 */
export function regretForBranch(
  delegateScorings: readonly DelegateScoring[],
  branchId: string,
  survivingBranchIds: readonly string[],
): Readonly<Record<string, number>> {
  const regret: Record<string, number> = {};
  for (const delegate of delegateScorings) {
    const cost = delegate.valuationProfile.costs[branchId];
    if (typeof cost !== "number") continue;
    const survivingCosts = survivingBranchIds
      .map((id) => delegate.valuationProfile.costs[id])
      .filter((c): c is number => typeof c === "number");
    if (survivingCosts.length === 0) continue;
    regret[delegate.personId] = cost - Math.min(...survivingCosts);
  }
  return regret;
}

/** The maximum regret any delegate feels for `branchId` — the figure
 * minimax regret minimises over the surviving branch set. */
export function maxRegretForBranch(
  delegateScorings: readonly DelegateScoring[],
  branchId: string,
  survivingBranchIds: readonly string[],
): number {
  const regret = regretForBranch(delegateScorings, branchId, survivingBranchIds);
  const values = Object.values(regret);
  return values.length > 0 ? Math.max(...values) : 0;
}

const SURVIVING_BRANCH_IDS = [BRANCH_IDS.suv, BRANCH_IDS.sedan] as const;

const COUNCIL_RESOLUTION_FIXTURE: CouncilResolution = {
  winningBranchId: BRANCH_IDS.suv,
  regretByPerson: { [PRIYA_ID]: 0, [MAYA_ID]: 3.0, [DADI_ID]: 0 },
  mostCostlyTo: MAYA_ID,
  mostFavorableTo: DADI_ID,
  concedingPersonIds: [MAYA_ID],
  eliminatedBranchIds: [BRANCH_IDS.hatchback],
} as const;

const RISK_REGISTER_FIXTURE: readonly string[] = [
  "Compact SUV's authorised service network is thin outside two centres, both over 12km away.",
  "Household's own history shows major-purchase maintenance underestimated by a wide margin before, budget a contingency, not just the sticker EMI.",
  "The sedan's rear door aperture is close to Dadi's minimum mobility threshold; it survived scoring but should be re-verified in person before any purchase, not assumed safe from the brief alone.",
  "Finance's affordability band assumes today's EMI capacity holds through Aarav's board-exam-year fee increase in March, not yet confirmed against the actual fee notice.",
] as const;

const COUNCIL_BRIEF_FIXTURE: CouncilBrief = {
  decisionId: DECISION_ID,
  question: COUNCIL_COMPOSITION_FIXTURE.question,
  specialistPositions: SPECIALIST_POSITIONS_FIXTURE,
  delegateScorings: DELEGATE_SCORINGS_FIXTURE,
  adversaryAttack: ADVERSARY_ATTACK_FIXTURE,
  resolution: COUNCIL_RESOLUTION_FIXTURE,
  riskRegister: RISK_REGISTER_FIXTURE,
} as const;

// ---------------------------------------------------------------------------
// Accessors — every consumer depends on these return types, never the
// fixture bodies above (see this file's DATA-LOADING BOUNDARY comment).
// ---------------------------------------------------------------------------

export function getCouncilComposition(): CouncilComposition {
  return COUNCIL_COMPOSITION_FIXTURE;
}

export function getCouncilBrief(): CouncilBrief {
  return COUNCIL_BRIEF_FIXTURE;
}

export function getSurvivingBranchIds(): readonly string[] {
  return SURVIVING_BRANCH_IDS;
}

// ---------------------------------------------------------------------------
// The explicit trade-off statement — computed prose, never a synthesized
// consensus paragraph (spec §12.2 design rule 2: positions are reported,
// never averaged by an LLM; this function averages nothing — it names the
// real winning branch, the real regret numbers on `CouncilResolution`, and
// quotes the named delegates' own already-written `DelegateScoring.reasoning`
// verbatim, matching spec §12.3 Phase 6's own worked phrasing: "Option B
// maximises joint welfare; it costs Priya most on parking convenience and
// gains Dad most on accessibility").
// ---------------------------------------------------------------------------

function formatRegret(regret: number): string {
  return regret.toFixed(1);
}

export function buildTradeOffStatement(brief: CouncilBrief): string {
  const { resolution, delegateScorings } = brief;
  const winnerLabel = branchLabel(resolution.winningBranchId);
  const sentences: string[] = [
    `${winnerLabel} is the household's minimax-regret pick among the surviving, hard-constraint-filtered options, the option that keeps the single worst regret any one delegate feels as small as possible, never the option with the highest combined score.`,
  ];

  const costlyId = resolution.mostCostlyTo;
  const costlyScoring = costlyId ? delegateScorings.find((d) => d.personId === costlyId) : undefined;
  if (costlyId && costlyScoring) {
    const regret = resolution.regretByPerson[costlyId];
    sentences.push(
      `It costs ${personLabel(costlyId)} most: a regret of ${formatRegret(regret)} against their own best surviving option. In their own words, "${costlyScoring.reasoning}"`,
    );
  } else {
    sentences.push("No single delegate carries the largest regret here, every convened delegate's regret for this option is equal.");
  }

  const favorableId = resolution.mostFavorableTo;
  const favorableScoring = favorableId ? delegateScorings.find((d) => d.personId === favorableId) : undefined;
  if (favorableId && favorableScoring) {
    const regret = resolution.regretByPerson[favorableId];
    sentences.push(
      `It favours ${personLabel(favorableId)} most: a regret of ${formatRegret(regret)} against their own best surviving option. In their own words, "${favorableScoring.reasoning}"`,
    );
  }

  if (resolution.concedingPersonIds.length > 0) {
    sentences.push(
      `${resolution.concedingPersonIds.map(personLabel).join(", ")} ${resolution.concedingPersonIds.length === 1 ? "is" : "are"} recorded as conceding on this decision, a real, permanent entry on the household's concession ledger, not a one-off complaint.`,
    );
  }

  return sentences.join(" ");
}
