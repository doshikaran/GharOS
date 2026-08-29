/**
 * TypeScript mirrors of the Phase 7 Household Ledger agent output shapes
 * (PHASES.md Phase 7, E4 work item — "Ledger view; recovered-money
 * counter; dispute UI; payroll review showing the register image beside
 * the computed figure").
 *
 * Source of truth, read directly rather than guessed at:
 *   - `backend/app/agents/ledger/types.py` — `ReconciliationFinding`,
 *     `LeakageAssessmentRequest`, `LeakageFinding`, `RecoveryDraft`,
 *     `ConflictingFigure`, `DisputePresentation`, `UnresolvedMark`,
 *     `PayrollResult`.
 *   - `backend/app/solvers/salary_calculator.py` — `SalaryCalculationResult`.
 *
 * These contracts are owned by E2 (`backend/app/agents/`) and E1
 * (`backend/app/solvers/`). This file mirrors their shape field-for-field;
 * it never redefines it. Field names are camelCase, following
 * `lib/approvals.ts`'s established convention for a fixture/wire seam —
 * every field maps 1:1 to its snake_case Python name.
 *
 * **DATA-LOADING BOUNDARY (this phase's brief, documented per its own
 * instructions).** Unlike `lib/graph-api.ts` / `lib/ledger-transactions.ts`
 * (real, live `/graph/snapshot` data), none of the five shapes above have
 * a REST endpoint this phase — no role built one; Phase 7's backend work
 * was agents + tools + solvers, not a new API surface. Every `get*()`
 * function below is a fixture-backed seam, following the exact precedent
 * `lib/approvals.ts` set in Phase 5: realistic, richly-varied data typed
 * exactly as the real backend shape, so every consumer component depends
 * only on the return type, never the fixture body — swapping the body for
 * a real fetch later is a one-function change here, not a rewrite of any
 * consumer.
 *
 * The fixture data below is deliberately continuous with
 * `backend/seeds/demo_household.py` — the same household (Priya, Aarav,
 * Dadi, Maya; Sunrise Apartments Society; FreshMart; Mehta Pharmacy) and,
 * wherever the real seed already has the relevant node, the *same* real
 * node id (`commitment-society-maintenance`, `ledger-maintenance-debit`,
 * `ledger-maya-advance`, `attendance-maya-2026-08`, `doc-attendance-register`,
 * `obligation-pay-maya-salary`) — not a coincidence, so a judge exploring
 * both the live graph and this ledger view sees one continuous household,
 * never two unrelated demos.
 */

// ---------------------------------------------------------------------------
// A28 — Reconciliation Agent output shape
// ---------------------------------------------------------------------------

export type ReconciliationFindingKind =
  | "duplicate"
  | "price_change"
  | "recurrence_detected"
  | "sms_ledger_mismatch"
  | "dues_mismatch"
  | "salary_reconciled"
  | "salary_mismatch";

export interface ReconciliationFinding {
  readonly kind: ReconciliationFindingKind;
  readonly commitmentId: string | null;
  readonly subjectEventIds: readonly string[];
  readonly explanation: string;
  readonly evidence: Readonly<Record<string, string>>;
  readonly confidence: number;
  readonly requiresDisputeBranch: boolean;
}

// ---------------------------------------------------------------------------
// A29 — Leakage Detection output shapes
// ---------------------------------------------------------------------------

export type LeakageVerdict = "leakage" | "worth_keeping" | "ambiguous";

/**
 * Mirrors `LeakageAssessmentRequest` — A29's *input*, not one of the five
 * output shapes this phase's brief names, but included here (unmodified,
 * every field mirrored) because it is the only place the real amount and
 * cadence A29 reasoned against live — `LeakageFinding` itself carries
 * neither, and the recovered-money counter cannot honestly compute an
 * annualised figure without them.
 */
export interface LeakageAssessmentRequest {
  readonly commitmentId: string;
  readonly label: string;
  readonly counterparty: string;
  readonly amount: number;
  readonly cadence: string;
  /** `[occurredAtIso, price][]`, oldest first. */
  readonly priceHistory: readonly (readonly [string, number])[];
  readonly lastUsedAt: string | null;
  readonly status: "active" | "paused" | "cancelled";
  readonly householdPriorities: string;
  /** Reference "today" the finding was computed against, ISO 8601. */
  readonly now: string;
}

export interface LeakageFinding {
  readonly commitmentId: string;
  readonly verdict: LeakageVerdict;
  readonly reasoning: string;
  readonly daysSinceLastUsed: number | null;
  readonly priceChangePct: number | null;
  readonly confidence: number;
  readonly evidence: Readonly<Record<string, string>>;
}

// ---------------------------------------------------------------------------
// A30 — Recovery Drafting output shape
// ---------------------------------------------------------------------------

export type RecoveryDraftKind = "cancellation" | "price_adjustment_request" | "dispute_filing" | "refund_claim";

export interface RecoveryDraft {
  readonly targetVendor: string;
  readonly ask: string;
  readonly messageText: string;
  readonly draftKind: RecoveryDraftKind;
  readonly confidence: number;
  readonly reasoning: string;
}

/**
 * UI-only display grouping — **not** one of the five mirrored backend
 * shapes. `RecoveryDraft` itself carries no back-reference to the
 * `LeakageFinding` it was drafted from (a real, honest gap: A30's own
 * `RecoveryDraftRequest` is built by its caller from a reduction of the
 * finding, never a stored link — see `backend/app/agents/ledger/types.py`'s
 * `RecoveryDraftRequest` docstring). This is the same join a real
 * orchestrator calling A29 then A30 would perform; grouping it here once
 * lets every consumer component render a case without re-deriving the
 * pairing itself.
 */
export interface LeakageCase {
  readonly request: LeakageAssessmentRequest;
  readonly finding: LeakageFinding;
  readonly recoveryDraft: RecoveryDraft | null;
}

// ---------------------------------------------------------------------------
// A32 — Dispute Branch output shapes
// ---------------------------------------------------------------------------

export interface ConflictingFigure {
  readonly sourceLabel: string;
  readonly amount: number;
  readonly currency: string;
  readonly reportedAt: string;
  readonly evidenceEventId: string;
  readonly evidenceText: string;
}

export interface DisputePresentation {
  readonly subject: string;
  readonly figureA: ConflictingFigure;
  readonly figureB: ConflictingFigure;
  readonly discrepancyAmount: number;
  readonly context: string;
  readonly confidence: number;
  readonly escalatedTo: "human_resolution";
}

// ---------------------------------------------------------------------------
// A34 — Staff Payroll output shapes (+ E1's deterministic salary solver)
// ---------------------------------------------------------------------------

export interface SalaryCalculationResult {
  readonly staffPersonId: string;
  readonly month: string;
  readonly currency: string;
  readonly daysWorked: number;
  readonly daysAbsent: number;
  readonly daysOnLeaveUnpaid: number;
  readonly dailyRate: number;
  readonly grossAmount: number;
  readonly totalAdvancesDeducted: number;
  readonly advanceEventIds: readonly string[];
  readonly netSalaryDue: number;
  readonly flooredAtZero: boolean;
}

export interface UnresolvedMark {
  readonly day: string;
  readonly reason: string;
}

export interface PayrollResult {
  readonly staffPersonId: string;
  readonly month: string;
  readonly salary: SalaryCalculationResult | null;
  readonly needsHumanReview: boolean;
  readonly unresolvedMarks: readonly UnresolvedMark[];
  readonly reviewReason: string | null;
  readonly registerImageRef: string | null;
  readonly obligationNodeId: string | null;
  readonly confidence: number;
  readonly reasoning: string;
  readonly modelTier: "pro" | "deterministic";
}

// ---------------------------------------------------------------------------
// Reference instant the fixtures below are written relative to — matches
// `backend/seeds/demo_household.py`'s `NOW` and `lib/approvals.ts`'s own
// fixture reference instant, so every fixture across every phase reads as
// one continuous household.
// ---------------------------------------------------------------------------

const NOW_ISO = "2026-08-22T09:00:00Z";
const NOW = new Date(NOW_ISO);

function daysAgoIso(days: number): string {
  return new Date(NOW.getTime() - days * 24 * 60 * 60 * 1000).toISOString();
}

// ---------------------------------------------------------------------------
// Reconciliation findings (A28)
// ---------------------------------------------------------------------------

const RECONCILIATION_FINDINGS_FIXTURE: readonly ReconciliationFinding[] = [
  // Silent price hike on a real, live commitment (spec: "Silent price hike
  // detected from price history") — the exact 2300 -> 2500 rise already
  // seeded on `commitment-society-maintenance` in demo_household.py.
  {
    kind: "price_change",
    commitmentId: "commitment-society-maintenance",
    subjectEventIds: ["ledger-maintenance-debit"],
    explanation:
      "Sunrise Apartments Society's monthly maintenance rose from ₹2,300 to ₹2,500 over the last year, an 8.7% increase with no linked AGM resolution on file.",
    evidence: { old_price: "2300.00", new_price: "2500.00", change_pct: "8.7%" },
    confidence: 0.88,
    requiresDisputeBranch: false,
  },
  // Silent-renewal finder (spec's "novel recurrences").
  {
    kind: "recurrence_detected",
    commitmentId: "commitment-cloudtv-premium",
    subjectEventIds: ["ledger-cloudtv-debit-jul", "ledger-cloudtv-debit-aug"],
    explanation:
      "Two consecutive ₹499 debits to the same UPI handle on the 3rd of each month were not linked to any known recurring commitment, recorded as a newly-detected series.",
    evidence: { counterparty: "CLOUDTV DIGITAL", months_observed: "2" },
    confidence: 0.81,
    requiresDisputeBranch: false,
  },
  // Duplicate charge detection.
  {
    kind: "duplicate",
    commitmentId: null,
    subjectEventIds: ["ledger-freshmart-duplicate-1", "ledger-freshmart-duplicate-2"],
    explanation:
      "Two ₹1,240 debits to FRESHMART GROCERY landed four minutes apart on 18 August, the second matches no separate purchase-item list of its own.",
    evidence: { amount: "1240.00", minutes_apart: "4" },
    confidence: 0.86,
    requiresDisputeBranch: false,
  },
  // SMS-vs-ledger mismatch -> dispute branch, never auto-resolved.
  {
    kind: "sms_ledger_mismatch",
    commitmentId: "commitment-society-maintenance",
    subjectEventIds: ["ledger-maintenance-debit"],
    explanation:
      "August's UPI SMS confirmation states ₹2,500 debited under reference 400912345678, but the bank statement ledger entry for the same reference shows ₹2,650, the two channels disagree.",
    evidence: { sms_amount: "2500.00", ledger_amount: "2650.00", reference: "400912345678" },
    confidence: 0.65,
    requiresDisputeBranch: true,
  },
  // Salary mismatch -> dispute branch (pairs with the second dispute below).
  {
    kind: "salary_mismatch",
    commitmentId: null,
    subjectEventIds: ["ledger-maya-salary-august"],
    explanation:
      "The attendance register computes Maya's August net salary at ₹9,000 after the ₹2,000 advance already paid, but the recorded SALARY payment event shows ₹11,000 with no linked advance deduction, a ₹2,000 gap.",
    evidence: { computed_net: "9000.00", recorded_payment: "11000.00", advance_already_paid: "2000.00" },
    confidence: 0.7,
    requiresDisputeBranch: true,
  },
  // The clean-match case, recorded just as auditably as a mismatch.
  {
    kind: "salary_reconciled",
    commitmentId: null,
    subjectEventIds: ["ledger-maya-salary-july"],
    explanation:
      "July's recorded SALARY payment of ₹10,500 matches the attendance-register-computed figure exactly, no discrepancy found.",
    evidence: { computed_net: "10500.00", recorded_payment: "10500.00" },
    confidence: 0.95,
    requiresDisputeBranch: false,
  },
];

/** Fixture-backed seam — see this module's DATA-LOADING BOUNDARY comment. */
export function getReconciliationFindings(): ReconciliationFinding[] {
  return [...RECONCILIATION_FINDINGS_FIXTURE];
}

// ---------------------------------------------------------------------------
// Leakage + recovery cases (A29 + A30)
// ---------------------------------------------------------------------------

const LEAKAGE_CASES_FIXTURE: readonly LeakageCase[] = [
  // Leakage #1 — unused, quietly-more-expensive subscription: cancel.
  {
    request: {
      commitmentId: "commitment-cloudtv-premium",
      label: "CloudTV Premium",
      counterparty: "CloudTV Digital Services",
      amount: 499.0,
      cadence: "monthly",
      priceHistory: [
        [daysAgoIso(365), 399.0],
        [daysAgoIso(30), 499.0],
      ],
      lastUsedAt: null,
      status: "active",
      householdPriorities: "Cutting non-essential spend this quarter after the society maintenance hike.",
      now: NOW_ISO,
    },
    finding: {
      commitmentId: "commitment-cloudtv-premium",
      verdict: "leakage",
      reasoning:
        "No household member has logged into CloudTV in the entire usage window on file, and the price rose 25% over the past year, an unused, quietly-more-expensive subscription with no stated household priority justifying it.",
      daysSinceLastUsed: null,
      priceChangePct: 25.06,
      confidence: 0.84,
      evidence: { last_login: "never recorded", price_change_pct: "25.1%" },
    },
    recoveryDraft: {
      targetVendor: "CloudTV Digital Services",
      ask: "Cancel the CloudTV Premium membership effective immediately.",
      messageText:
        "Hello CloudTV team, please cancel the Premium membership on this account effective immediately, we have not used the service and no longer wish to continue the subscription. Please confirm the cancellation and that no further payments will be collected.",
      draftKind: "cancellation",
      confidence: 0.88,
      reasoning:
        "No usage signal exists for this service across the entire window on file, and it carries no stated household priority, a straightforward cancellation, not a negotiation.",
    },
  },
  // Leakage #2 — forgotten membership, life change made it obsolete: cancel.
  {
    request: {
      commitmentId: "commitment-fitcircle-gym",
      label: "Fit Circle Gym membership",
      counterparty: "Fit Circle Gym, Andheri",
      amount: 1800.0,
      cadence: "monthly",
      priceHistory: [[daysAgoIso(200), 1800.0]],
      lastUsedAt: daysAgoIso(95),
      status: "active",
      householdPriorities: "Priya switched to home workouts after Dadi moved in and hasn't mentioned the gym since March.",
      now: NOW_ISO,
    },
    finding: {
      commitmentId: "commitment-fitcircle-gym",
      verdict: "leakage",
      reasoning:
        "Card-swipe usage records show no visit in 95 days, and Priya's own household notes describe switching to home workouts months ago, this reads as a forgotten membership, not a paused-but-wanted one.",
      daysSinceLastUsed: 95,
      priceChangePct: null,
      confidence: 0.79,
      evidence: { last_visit_days_ago: "95", household_note: "switched to home workouts in March" },
    },
    recoveryDraft: {
      targetVendor: "Fit Circle Gym, Andheri",
      ask: "Cancel the membership effective the next billing cycle, per the 30-day notice clause.",
      messageText:
        "Hello Fit Circle team, please treat this as 30 days' notice to cancel the membership on this account, effective the next billing cycle per the membership agreement's notice clause. Please confirm the cancellation date and that no further debits will be attempted after it.",
      draftKind: "cancellation",
      confidence: 0.82,
      reasoning:
        "Ninety-five days with no visit, alongside a real household note explaining the switch to home workouts, clears the bar for a cancellation request rather than a lower-confidence flag.",
    },
  },
  // Leakage #3 — service is used and wanted, but the price hike itself is
  // the leakage: price-adjustment request, not a cancellation.
  {
    request: {
      commitmentId: "commitment-speedlink-broadband",
      label: "SpeedLink Fiber broadband",
      counterparty: "SpeedLink Broadband Services",
      amount: 1499.0,
      cadence: "monthly",
      priceHistory: [
        [daysAgoIso(365), 999.0],
        [daysAgoIso(60), 1499.0],
      ],
      lastUsedAt: daysAgoIso(1),
      status: "active",
      householdPriorities: "Aarav's classes run online three days a week, broadband is essential, but the price jump is worth challenging.",
      now: NOW_ISO,
    },
    finding: {
      commitmentId: "commitment-speedlink-broadband",
      verdict: "leakage",
      reasoning:
        "SpeedLink's ₹999 to ₹1,499 hike (50%) has no matching plan or speed change, and SpeedLink's own published rate for new customers on the same plan is ₹1,199, worth challenging even though the service itself is used daily and essential to keep.",
      daysSinceLastUsed: 1,
      priceChangePct: 50.05,
      confidence: 0.83,
      evidence: { new_customer_rate: "1199.00", current_rate: "1499.00", price_change_pct: "50.1%" },
    },
    recoveryDraft: {
      targetVendor: "SpeedLink Broadband Services",
      ask: "Match the new-customer rate of ₹1,199/month for the same plan, or roll back the unexplained increase.",
      messageText:
        "Hello SpeedLink team, our plan's monthly rate rose from ₹999 to ₹1,499 without a change in speed or terms, while your website currently advertises ₹1,199/month for new customers on the identical plan. As a long-standing customer, please match the new-customer rate or explain the basis for the increase.",
      draftKind: "price_adjustment_request",
      confidence: 0.8,
      reasoning:
        "The service is genuinely used daily and essential to keep, the ask targets only the unexplained portion of the increase, not the connection itself.",
    },
  },
  // Worth keeping — tied directly to a real care obligation, no draft.
  {
    request: {
      commitmentId: "commitment-mehta-delivery-plan",
      label: "Mehta Pharmacy home-delivery plan",
      counterparty: "Mehta Pharmacy",
      amount: 199.0,
      cadence: "monthly",
      priceHistory: [[daysAgoIso(180), 199.0]],
      lastUsedAt: daysAgoIso(2),
      status: "active",
      householdPriorities: "Dadi's prescriptions are delivered weekly under this plan, core to her care routine.",
      now: NOW_ISO,
    },
    finding: {
      commitmentId: "commitment-mehta-delivery-plan",
      verdict: "worth_keeping",
      reasoning:
        "Delivery logs show weekly use tied directly to Dadi's blood-pressure prescription refills, and the price hasn't moved in six months, exactly the kind of recurring spend the household's stated priorities describe as non-negotiable.",
      daysSinceLastUsed: 2,
      priceChangePct: null,
      confidence: 0.91,
      evidence: { last_delivery_days_ago: "2", tied_obligation: "obligation-renew-prescription" },
    },
    recoveryDraft: null,
  },
  // Ambiguous — no usage signal applies, no stated household position.
  {
    request: {
      commitmentId: "commitment-society-event-fund",
      label: "Sunrise Society Diwali event fund",
      counterparty: "Sunrise Apartments Society",
      amount: 500.0,
      cadence: "yearly",
      priceHistory: [[daysAgoIso(365), 500.0]],
      lastUsedAt: null,
      status: "active",
      householdPriorities: "No stated position on record for optional society contributions.",
      now: NOW_ISO,
    },
    finding: {
      commitmentId: "commitment-society-event-fund",
      verdict: "ambiguous",
      reasoning:
        "There is no usage signal for a community contribution like this one, it isn't 'used' the way a subscription is, and no household-priorities note takes a position on optional society spend either way. Flagging for a human read rather than guessing.",
      daysSinceLastUsed: null,
      priceChangePct: null,
      confidence: 0.42,
      evidence: { usage_signal: "not applicable, community contribution", household_position: "none on record" },
    },
    recoveryDraft: null,
  },
];

/** Fixture-backed seam — see this module's DATA-LOADING BOUNDARY comment. */
export function getLeakageCases(): LeakageCase[] {
  return [...LEAKAGE_CASES_FIXTURE];
}

// ---------------------------------------------------------------------------
// Recovered-money counter (spec §10.7's demo metric)
// ---------------------------------------------------------------------------

/**
 * Cadence -> occurrences-per-year, a UI-layer presentation/computation
 * policy call (`RecurringCommitment.cadence` / `LeakageAssessmentRequest.cadence`
 * are free-text on the frozen backend contract, not an enum) — documented
 * explicitly rather than silently guessed, mirroring
 * `app.solvers.salary_calculator`'s own "explicit, documented policy call"
 * convention. An unrecognised cadence is conservatively treated as already
 * a per-year figure (multiplier 1) rather than inflated by a guessed
 * multiplier.
 */
const CADENCE_OCCURRENCES_PER_YEAR: Readonly<Record<string, number>> = {
  weekly: 52,
  biweekly: 26,
  fortnightly: 26,
  monthly: 12,
  quarterly: 4,
  yearly: 1,
  annual: 1,
  annually: 1,
};

function annualisationFactor(cadence: string): number {
  return CADENCE_OCCURRENCES_PER_YEAR[cadence.trim().toLowerCase()] ?? 1;
}

/**
 * The recoverable annual amount for one leakage case — a second, documented
 * policy call: a case whose drafted claim asks to **cancel** the commitment
 * counts its full annualised amount as leakage (the whole spend is wasted);
 * a case whose claim only asks for a **price adjustment** (the service is
 * kept) counts only the annualised size of the unexplained price hike
 * (oldest vs. newest `priceHistory` entry) — never the full bill, since the
 * base amount would be paid either way. A case with no draft yet, or fewer
 * than two `priceHistory` points to measure a hike from, falls back to its
 * full annualised amount.
 */
function annualLeakageAmount(leakageCase: LeakageCase): number {
  const { request, recoveryDraft } = leakageCase;
  if (recoveryDraft?.draftKind === "price_adjustment_request" && request.priceHistory.length >= 2) {
    const oldest = request.priceHistory[0][1];
    const newest = request.priceHistory[request.priceHistory.length - 1][1];
    const hike = Math.max(0, newest - oldest);
    return hike * annualisationFactor(request.cadence);
  }
  return request.amount * annualisationFactor(request.cadence);
}

export interface RecoveredMoneySummary {
  /** Sum of `annualLeakageAmount` across every `verdict === "leakage"` case
   * — a real, honestly-computed figure from the data, never a fixed
   * display string. */
  readonly annualLeakageTotal: number;
  readonly currency: string;
  /** Count of leakage-verdict cases that have produced a drafted claim
   * (`recoveryDraft !== null`) — spec §10.7's "three claims drafted,
   * awaiting approval". */
  readonly draftsAwaitingApproval: number;
  /** Total count of `verdict === "leakage"` cases, drafted or not. */
  readonly leakageCaseCount: number;
}

/**
 * Computes the spec §10.7 demo metric ("found ₹X/year of leakage — three
 * claims drafted, awaiting approval") from real `LeakageCase` data — every
 * number here is derived, never hardcoded.
 */
export function computeRecoveredMoneySummary(cases: readonly LeakageCase[]): RecoveredMoneySummary {
  const leakageCases = cases.filter((c) => c.finding.verdict === "leakage");
  const annualLeakageTotal = leakageCases.reduce((total, c) => total + annualLeakageAmount(c), 0);
  const draftsAwaitingApproval = leakageCases.filter((c) => c.recoveryDraft !== null).length;
  return {
    annualLeakageTotal,
    // The household's ledger is INR throughout this demo household (see
    // `lib/approvals.ts`'s identical documented assumption) — every
    // fixture commitment above is INR-denominated.
    currency: "INR",
    draftsAwaitingApproval,
    leakageCaseCount: leakageCases.length,
  };
}

// ---------------------------------------------------------------------------
// Dispute presentations (A32) — the two `requires_dispute_branch: true`
// findings above, presented with equal weight and no resolve affordance.
// ---------------------------------------------------------------------------

const DISPUTE_PRESENTATIONS_FIXTURE: readonly DisputePresentation[] = [
  {
    subject: "August society maintenance debit",
    figureA: {
      sourceLabel: "SMS notification",
      amount: 2500.0,
      currency: "INR",
      reportedAt: "2026-08-22T09:12:00Z",
      evidenceEventId: "ledger-maintenance-debit",
      evidenceText:
        "UPI SMS, 22 Aug 09:12 IST: 'Rs 2500.00 debited from A/c XX4821 to SUNRISE SOCIETY MAINT. Ref 400912345678.'",
    },
    figureB: {
      sourceLabel: "ledger record",
      amount: 2650.0,
      currency: "INR",
      reportedAt: "2026-08-22T18:00:00Z",
      evidenceEventId: "ledger-maintenance-debit",
      evidenceText:
        "Bank statement line for reference 400912345678: 'SUNRISE SOCIETY MAINT, INR 2,650.00, 22 Aug.'",
    },
    discrepancyAmount: 150.0,
    context:
      "Both figures reference the same UPI transaction reference number and the same day's maintenance payment. Neither channel is inherently more reliable, SMS parsing can mis-read a digit, and a bank statement's line aggregation can occasionally merge two nearby debits. Left for a human to resolve against the bank app or a call to the society office.",
    confidence: 0.65,
    escalatedTo: "human_resolution",
  },
  {
    subject: "Maya's August salary payment",
    figureA: {
      sourceLabel: "attendance register",
      amount: 9000.0,
      currency: "INR",
      reportedAt: "2026-08-21T00:00:00Z",
      evidenceEventId: "attendance-maya-2026-08",
      evidenceText:
        "22 days present at ₹500/day = ₹11,000 gross, minus the ₹2,000 advance already recorded on 12 Aug (ledger-maya-advance) = ₹9,000 net due.",
    },
    figureB: {
      sourceLabel: "recorded SALARY payment",
      amount: 11000.0,
      currency: "INR",
      reportedAt: "2026-08-22T00:00:00Z",
      evidenceEventId: "ledger-maya-salary-august",
      evidenceText: "SALARY ledger event dated 22 Aug records a payment of ₹11,000, with no linked advance deduction.",
    },
    discrepancyAmount: 2000.0,
    context:
      "The computed figure and the recorded payment differ by exactly the amount of Maya's already-paid advance, suggesting the deduction was missed when the payment was made, but the household should confirm with Maya directly before treating this as an overpayment, since the register's own handwriting could also be misread.",
    confidence: 0.7,
    escalatedTo: "human_resolution",
  },
];

/** Fixture-backed seam — see this module's DATA-LOADING BOUNDARY comment. */
export function getDisputePresentations(): DisputePresentation[] {
  return [...DISPUTE_PRESENTATIONS_FIXTURE];
}

// ---------------------------------------------------------------------------
// Payroll results (A34 + the deterministic salary solver)
// ---------------------------------------------------------------------------

const PAYROLL_RESULTS_FIXTURE: readonly PayrollResult[] = [
  // Clean register, no review needed — the real seeded August attendance
  // numbers (22 present / 2 absent / 1 leave / ₹2,000 advance), a real
  // daily rate applied on top. Ties exactly to the salary-mismatch dispute
  // above: this IS the correct ₹9,000 figure the recorded ₹11,000 payment
  // disagrees with.
  {
    staffPersonId: "person-maya",
    month: "2026-08",
    salary: {
      staffPersonId: "person-maya",
      month: "2026-08",
      currency: "INR",
      daysWorked: 22,
      daysAbsent: 2,
      daysOnLeaveUnpaid: 1,
      dailyRate: 500.0,
      grossAmount: 11000.0,
      totalAdvancesDeducted: 2000.0,
      advanceEventIds: ["ledger-maya-advance"],
      netSalaryDue: 9000.0,
      flooredAtZero: false,
    },
    needsHumanReview: false,
    unresolvedMarks: [],
    reviewReason: null,
    // Real, live SOURCE_DOCUMENT id from `backend/seeds/demo_household.py`
    // — `RegisterImagePanel` fetches this from the real, live
    // `/documents/{id}/raw` endpoint when the backend is running.
    registerImageRef: "doc-attendance-register",
    obligationNodeId: "obligation-pay-maya-salary",
    confidence: 0.88,
    reasoning:
      "The register's marks for August were legible throughout, 22 present, 2 absent, 1 leave day, and the ₹2,000 advance recorded on 12 Aug is the only ADVANCE-kind ledger event this period, so the deterministic solver's net figure is trusted without a human review.",
    modelTier: "deterministic",
  },
  // Needs human review — an ambiguous mark, no guessed figure produced.
  // `registerImageRef` deliberately names a document id that does not
  // exist in the live backend — this is the fixture's "static image
  // otherwise, clearly labeled" path (see `RegisterImagePanel`).
  {
    staffPersonId: "person-maya",
    month: "2026-07",
    salary: null,
    needsHumanReview: true,
    unresolvedMarks: [
      {
        day: "18",
        reason:
          "Mark on the 18th is smudged, could be a present tick or an absent cross. A34's own Pro-tier re-read scored both interpretations within 0.05 of each other, below the confidence floor for either.",
      },
    ],
    reviewReason:
      "One day's mark (18 Jul) could not be confidently interpreted even after a Pro-tier re-read attempt, the household should check the photographed register directly before July's salary is computed.",
    registerImageRef: "doc-attendance-register-2026-07",
    obligationNodeId: null,
    confidence: 0.58,
    reasoning:
      "Every other day in July's register read cleanly, but the 18th's mark sits right at the ambiguity threshold, rather than guess, this is held for a human to look at the actual photograph.",
    modelTier: "pro",
  },
];

/** Fixture-backed seam — see this module's DATA-LOADING BOUNDARY comment. */
export function getPayrollResults(): PayrollResult[] {
  return [...PAYROLL_RESULTS_FIXTURE];
}
