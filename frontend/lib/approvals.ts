/**
 * TypeScript mirror of the frozen backend action/approval contracts that
 * the Approval Gate UI renders (PHASES.md Phase 5, E4 work item —
 * "Approval queue: proposed action, reasoning, evidence, confidence,
 * consequence-if-wrong" and "Escalation surface").
 *
 * Source of truth, read directly rather than guessed at:
 *   - `contracts/actions.py` — `RiskTier` (R0-R4, docstrings copied verbatim
 *     into `RISK_TIER_POLICY` below) and `EvidenceBundle` (`proposed_action`,
 *     `reasoning`, `evidence_consulted`, `confidence`, `consequence_if_wrong`).
 *   - `contracts/graph_types.py` — `ApprovalStatus`
 *     (pending/approved/rejected/expired) and `ApprovalRequest`
 *     (`proposed_action_summary`, `evidence_bundle`, `risk_tier`,
 *     `confidence`, `consequence_if_wrong`, `status`, `expires_at`).
 *
 * These contracts are owned exclusively by the CTO (`contracts/`). This
 * file mirrors their shape; it never redefines it.
 *
 * **A known contract seam, documented rather than silently resolved:**
 * `contracts/graph_types.py:ApprovalRequest.evidence_bundle` is typed
 * `dict[str, str]` — a loose bag — even though the evidence bundle it is
 * meant to carry is fully structured in `contracts/actions.py:EvidenceBundle`
 * (with a real `evidence_consulted: tuple[str, ...]` list). Reconciling
 * that gap is a CTO-owned contract change, not something E4 may do
 * unilaterally. Below, `ApprovalRequestWire` mirrors the loose
 * `dict[str, str]` shape faithfully for the record; `ApprovalQueueItem` —
 * the shape every component in `components/approvals/` actually renders —
 * composes the wire fields with the properly-typed `EvidenceBundle`,
 * because rendering "the evidence consulted as a real list, not
 * truncated/hidden" (this phase's brief) requires the structured shape,
 * and that structured shape is exactly what a reconciled backend would
 * eventually send. `provenance` (present on the real `ApprovalRequest`
 * node) is intentionally left out of this mirror — the approval queue
 * does not render it; the graph/provenance inspector that does is Phase 6
 * (Frontend Shell & Graph Visualisation) work, not this phase's.
 */

// ---------------------------------------------------------------------------
// RiskTier (contracts/actions.py) — spec §18.1 is the policy source of truth
// ---------------------------------------------------------------------------

export type RiskTier = "R0" | "R1" | "R2" | "R3" | "R4";

export interface RiskTierPolicy {
  readonly tier: RiskTier;
  /** Short label matching spec §18.1's table exactly, e.g. "R0 — Silent". */
  readonly label: string;
  readonly definition: string;
  readonly policy: string;
  readonly examples: readonly string[];
}

/**
 * The real policy meaning behind each tier code (spec §18.1), copied
 * verbatim from `contracts/actions.py`'s `RiskTier` docstrings and the
 * spec's tier table. Every surface that shows a risk tier code must show
 * this meaning alongside it — a bare "R3" chip teaches a judge nothing.
 */
export const RISK_TIER_POLICY: Record<RiskTier, RiskTierPolicy> = {
  R0: {
    tier: "R0",
    label: "R0 — Silent",
    definition: "Reversible, internal, no external effect.",
    policy: "Executes immediately; logged. No approval requested.",
    examples: ["Graph write", "Calendar entry", "Information prep"],
  },
  R1: {
    tier: "R1",
    label: "R1 — Notify",
    definition: "Reversible, low-impact, visible.",
    policy: "Executes immediately; household notified. No approval requested.",
    examples: ["Draft message", "Propose menu substitution", "Shopping list"],
  },
  R2: {
    tier: "R2",
    label: "R2 — Approve",
    definition: "External communication, non-financial.",
    policy: "Requires approval before executing.",
    examples: ["Send message outside household", "Submit a form", "Place a call"],
  },
  R3: {
    tier: "R3",
    label: "R3 — Explicit approve",
    definition: "Any movement of money.",
    policy: "Requires approval, with the full evidence bundle shown, before executing.",
    examples: ["Pay dues", "Pay salary", "Cancel mandate", "File dispute"],
  },
  R4: {
    tier: "R4",
    label: "R4 — Escalate only",
    definition: "Irreversible, high-stakes, emotionally loaded.",
    policy: "Never auto-executes. The Council never resolves this tier — it produces a brief; a human decides.",
    examples: [
      "Relocation",
      "Property purchase",
      "Care arrangements",
      "Ending staff employment",
      "Medical choices",
    ],
  },
};

export const RISK_TIER_ORDER: readonly RiskTier[] = ["R0", "R1", "R2", "R3", "R4"];

// ---------------------------------------------------------------------------
// ApprovalStatus (contracts/graph_types.py)
// ---------------------------------------------------------------------------

export type ApprovalStatus = "pending" | "approved" | "rejected" | "expired";

// ---------------------------------------------------------------------------
// EvidenceBundle (contracts/actions.py) — "every approval request carries
// these five things, no exceptions" (spec §18.2)
// ---------------------------------------------------------------------------

export interface EvidenceBundle {
  readonly proposedAction: string;
  readonly reasoning: string;
  readonly evidenceConsulted: readonly string[];
  /** 0.0-1.0. */
  readonly confidence: number;
  readonly consequenceIfWrong: string;
}

// ---------------------------------------------------------------------------
// ApprovalRequest wire shape (contracts/graph_types.py), mirrored faithfully
// including its looser `evidence_bundle: dict[str, str]` field — see the
// file-level comment above for why `ApprovalQueueItem` does not use this
// field directly.
// ---------------------------------------------------------------------------

export interface ApprovalRequestWire {
  readonly id: string;
  readonly proposedActionSummary: string;
  readonly evidenceBundle: Readonly<Record<string, string>>;
  readonly riskTier: RiskTier;
  readonly confidence: number;
  readonly consequenceIfWrong: string;
  readonly status: ApprovalStatus;
  /** ISO 8601. Expiry escalates the request; it never auto-approves it. */
  readonly expiresAt: string;
}

/**
 * The shape every component in `components/approvals/` renders. Same wire
 * fields as `ApprovalRequestWire`, with `evidenceBundle` upgraded to the
 * fully-typed `EvidenceBundle` (see the contract-seam comment above).
 */
export interface ApprovalQueueItem extends Omit<ApprovalRequestWire, "evidenceBundle"> {
  readonly evidenceBundle: EvidenceBundle;
}

// ---------------------------------------------------------------------------
// Categorisation — shared by the approval queue and the escalation surface
// so both surfaces agree, structurally, on which item goes where.
// ---------------------------------------------------------------------------

/**
 * True if `item` must render as escalated rather than pending — either it
 * is already flagged `expired` by the backend, or (defensively, client
 * side) its `expiresAt` has passed while it is still marked `pending`
 * because the status-flip event has not landed yet. Spec §18.2: "approval
 * expiry escalates; never auto-approves" — this function is what makes
 * that true in the UI even under a stale `status` field, never just in
 * backend policy.
 */
export function isExpired(item: ApprovalQueueItem, now: Date = new Date()): boolean {
  if (item.status === "expired") return true;
  return item.status === "pending" && new Date(item.expiresAt).getTime() <= now.getTime();
}

/**
 * True if `item` belongs in the approve/reject queue: still pending, not
 * expired, and below R4 (R4 "never auto-executes; present options only" —
 * spec §18.1 — so it never gets an approve/reject affordance at all, at
 * any status; see `isEscalation`).
 */
export function needsApproval(item: ApprovalQueueItem, now: Date = new Date()): boolean {
  return item.riskTier !== "R4" && item.status === "pending" && !isExpired(item, now);
}

/**
 * True if `item` belongs on the escalation surface: every R4 request
 * (spec §18.1/§18.2 — the Council never resolves this tier, only humans
 * do) and every expired request, regardless of tier. This is deliberately
 * NOT "not needsApproval" — a resolved (approved/rejected) R2/R3 item is
 * neither actionable nor an escalation; see `isResolved`.
 */
export function isEscalation(item: ApprovalQueueItem, now: Date = new Date()): boolean {
  return item.riskTier === "R4" || isExpired(item, now);
}

/** True if `item` is a closed, non-escalated record — shown as history. */
export function isResolved(item: ApprovalQueueItem, now: Date = new Date()): boolean {
  return !needsApproval(item, now) && !isEscalation(item, now);
}

/** `en-IN`, since the household's currency and examples throughout this
 * project are Indian Rupee / IST-oriented. */
export function formatDateTime(iso: string): string {
  return new Intl.DateTimeFormat("en-IN", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "UTC",
  }).format(new Date(iso));
}

// ---------------------------------------------------------------------------
// Fixture data
// ---------------------------------------------------------------------------

/**
 * Reference instant the fixture below is written relative to (2026-08-22
 * 09:00 UTC) — matches `backend/seeds/demo_household.py`'s `NOW` so this
 * fixture reads as the same continuous household (Priya, Aarav, Dadi;
 * Sunrise Apartments Society; Mehta Pharmacy; Freshmart) rather than an
 * unrelated demo. Fixture timestamps below are literal ISO strings, not
 * computed off the real clock, so component tests stay deterministic
 * regardless of when they run.
 */
const APPROVAL_QUEUE_FIXTURE: readonly ApprovalQueueItem[] = [
  // R2 — pending. Placing a call: the outbound-concierge demo beat.
  {
    id: "approval-om-electricals-call",
    proposedActionSummary:
      "Call Om Electricals to confirm tomorrow's 4:00-5:00 PM slot to fix the geyser before Dadi's bath time.",
    riskTier: "R2",
    confidence: 0.88,
    consequenceIfWrong:
      "If unconfirmed, the free site-visit waiver lapses and Dadi goes another three days without hot water for her bath. Calling the wrong number risks disturbing an unrelated household.",
    status: "pending",
    expiresAt: "2026-08-22T11:00:00Z",
    evidenceBundle: {
      proposedAction:
        "Call Om Electricals to confirm tomorrow's 4:00-5:00 PM slot to fix the geyser before Dadi's bath time.",
      reasoning:
        "The vendor's email offers a free site visit only if confirmed within 24 hours. The household calendar has no conflicting obligation in that window, and this vendor has a track record of honouring booked slots, so calling now to confirm is the highest-value next step.",
      evidenceConsulted: [
        "Email from Om Electricals received 06:40 IST offering a 4:00-5:00 PM slot tomorrow, free site visit if confirmed within 24 hours",
        "Household calendar: no conflicting obligation for Priya between 3:30 PM and 5:30 PM tomorrow",
        "Vendor reliability score 0.85 from 4 prior jobs, average response time 6 hours",
      ],
      confidence: 0.88,
      consequenceIfWrong:
        "If unconfirmed, the free site-visit waiver lapses and Dadi goes another three days without hot water for her bath. Calling the wrong number risks disturbing an unrelated household.",
    },
  },

  // R3 — pending. Money movement: the strictest tier, evidence bundle required.
  {
    id: "approval-kamala-bai-salary",
    proposedActionSummary: "Pay Kamala Bai's August salary of ₹14,000 via the registered UPI mandate.",
    riskTier: "R3",
    confidence: 0.93,
    consequenceIfWrong:
      "Underpaying shorts a household employee who relies on this income to be paid on time; overpaying, or paying twice, is an unrecoverable UPI transfer beyond what the register actually supports.",
    status: "pending",
    expiresAt: "2026-08-23T03:00:00Z",
    evidenceBundle: {
      proposedAction: "Pay Kamala Bai's August salary of ₹14,000 via the registered UPI mandate.",
      reasoning:
        "The handwritten attendance register, photographed and OCR'd, shows 26 days present against the household's agreed monthly rate. No SALARY ledger event exists yet for this cycle under this idempotency key, so this would be the first and only debit for August.",
      evidenceConsulted: [
        "Handwritten payroll register photographed 21 Aug: 26 days marked present, 2 days leave, in Kamala Bai's own hand",
        "Household HR note: agreed monthly rate ₹14,000, unchanged since March",
        "Ledger check: no existing debit under idempotency key kamala-bai:salary:2026-08",
      ],
      confidence: 0.93,
      consequenceIfWrong:
        "Underpaying shorts a household employee who relies on this income to be paid on time; overpaying, or paying twice, is an unrecoverable UPI transfer beyond what the register actually supports.",
    },
  },

  // R2 — rejected. Resolved history: a human explicitly declined.
  {
    id: "approval-society-dispute-message",
    proposedActionSummary:
      "Send a message to the Sunrise Apartments Society WhatsApp group disputing the ₹2,400 'special maintenance' line item as undocumented.",
    riskTier: "R2",
    confidence: 0.68,
    consequenceIfWrong:
      "Raising an undeserved dispute publicly in the group could strain the relationship with the managing committee over a charge that may in fact be valid.",
    status: "rejected",
    expiresAt: "2026-08-20T18:00:00Z",
    evidenceBundle: {
      proposedAction:
        "Send a message to the Sunrise Apartments Society WhatsApp group disputing the ₹2,400 'special maintenance' line item as undocumented.",
      reasoning:
        "Two years of prior society notices on file each reference an AGM resolution number for any special levy; this one does not, which is unusual enough to flag — but publicly disputing it is a lower-confidence path than raising it privately first.",
      evidenceConsulted: [
        "Society notice (doc-society-notice) lists a ₹2,400 'special maintenance' line with no linked AGM resolution number",
        "24 months of prior notices on file: every previous special levy cites a resolution number",
      ],
      confidence: 0.68,
      consequenceIfWrong:
        "Raising an undeserved dispute publicly in the group could strain the relationship with the managing committee over a charge that may in fact be valid.",
    },
  },

  // R3 — approved. Resolved history: a human explicitly signed off.
  {
    id: "approval-sunrise-maintenance-payment",
    proposedActionSummary:
      "Pay Sunrise Apartments Society's extended-deadline maintenance due of ₹2,500 for August via the registered mandate.",
    riskTier: "R3",
    confidence: 0.95,
    consequenceIfWrong:
      "A missed or duplicate maintenance payment risks a late fee from the society or an unrecoverable double debit.",
    status: "approved",
    expiresAt: "2026-08-21T12:00:00Z",
    evidenceBundle: {
      proposedAction:
        "Pay Sunrise Apartments Society's extended-deadline maintenance due of ₹2,500 for August via the registered mandate.",
      reasoning:
        "The society extended August's due date by 7 days in its revised notice, superseding the original obligation. No debit has been recorded yet against this cycle's idempotency key.",
      evidenceConsulted: [
        "Obligation obligation-pay-maintenance-v2 due in 9 days, superseding the original due-in-2-days obligation after the society's deadline-extension notice",
        "Ledger check: no existing debit under idempotency key sunrise-society:maintenance:2026-08",
      ],
      confidence: 0.95,
      consequenceIfWrong:
        "A missed or duplicate maintenance payment risks a late fee from the society or an unrecoverable double debit.",
    },
  },

  // R0 — auto-cleared. Included per this phase's brief ("at least one
  // example per RiskTier value") to make the full tiering spectrum
  // legible; R0 never actually requests approval (spec §18.1: "Execute;
  // log"), so components must render this distinctly from a human decision.
  {
    id: "approval-log-fan-repair",
    proposedActionSummary: "Log the electrician's completed ceiling-fan repair and mark the obligation done.",
    riskTier: "R0",
    confidence: 0.9,
    consequenceIfWrong:
      "A wrong internal log entry only needs a graph correction — no money moved and nobody was contacted.",
    status: "approved",
    expiresAt: "2026-08-21T14:15:00Z",
    evidenceBundle: {
      proposedAction: "Log the electrician's completed ceiling-fan repair and mark the obligation done.",
      reasoning:
        "This is a graph write with no external effect — it executes immediately and is logged, per R0 policy. Shown here only so the full risk-tier spectrum is visible; no human approval was requested or required.",
      evidenceConsulted: [
        "Vendor confirmation SMS: 'Fan repaired, ₹350 collected' received 14:02 IST",
        "Matches open obligation obligation-fix-ceiling-fan, due the same day",
      ],
      confidence: 0.9,
      consequenceIfWrong:
        "A wrong internal log entry only needs a graph correction — no money moved and nobody was contacted.",
    },
  },

  // R1 — auto-cleared, notified. Ties to the seeded nut-allergy constraint
  // and the mixed-nuts purchase that contradicts it.
  {
    id: "approval-menu-substitution-note",
    proposedActionSummary:
      "Draft a note to the cook substituting tomorrow's snack from the mixed-nuts pack to roasted chana, given Aarav's nut allergy.",
    riskTier: "R1",
    confidence: 0.9,
    consequenceIfWrong:
      "Worst case, the cook prepares chana nobody asked for. The mixed-nuts pack is removed from circulation either way, so Aarav's safety is unaffected by getting this substitution wrong.",
    status: "approved",
    expiresAt: "2026-08-21T20:00:00Z",
    evidenceBundle: {
      proposedAction:
        "Draft a note to the cook substituting tomorrow's snack from the mixed-nuts pack to roasted chana, given Aarav's nut allergy.",
      reasoning:
        "Constraint constraint-nut-free is a hard constraint ('no nuts in the house, ever'), and Wednesday's Freshmart receipt line for a mixed-nuts snack pack contradicts it. Drafting a substitution note is reversible and low-impact, so it executes with notification rather than waiting on approval, per R1 policy.",
      evidenceConsulted: [
        "Constraint constraint-nut-free: hard severity, 'Aarav is severely allergic to nuts — no nuts in the house, ever' (Priya, school WhatsApp thread)",
        "Purchase item item-mixed-nuts contradicts constraint-nut-free at 0.90 confidence",
        "Cook's contact channel accepts text notes; substitution is fully reversible before tomorrow's snack time",
      ],
      confidence: 0.9,
      consequenceIfWrong:
        "Worst case, the cook prepares chana nobody asked for. The mixed-nuts pack is removed from circulation either way, so Aarav's safety is unaffected by getting this substitution wrong.",
    },
  },

  // R4 — pending, escalate-only. Never a proposal to approve; a Council
  // brief for the household to decide, per spec §18.1/§18.2.
  {
    id: "approval-redevelopment-buyback-brief",
    proposedActionSummary:
      "Whether to accept Sunrise Apartments Society's redevelopment buyback offer and relocate before the vacate deadline.",
    riskTier: "R4",
    confidence: 0.71,
    consequenceIfWrong:
      "Relocating on a weak valuation loses irrecoverable equity; refusing and missing the deadline risks forced vacancy on worse terms. Either error is largely irreversible and affects every household member, including Dadi's care continuity.",
    status: "pending",
    expiresAt: "2026-09-21T09:00:00Z",
    evidenceBundle: {
      proposedAction:
        "Whether to accept Sunrise Apartments Society's redevelopment buyback offer and relocate before the vacate deadline.",
      reasoning:
        "This is irreversible, high-stakes, and emotionally loaded for every household member — exactly the category the Council does not resolve. It produces a brief, laid out here, for the household to decide.",
      evidenceConsulted: [
        "Redevelopment notice sets a 90-day vacate deadline with a buyback price 12% under the last two independent valuations on file",
        "Dadi's nap-window constraint and medical-proxy arrangements both depend on the current flat's proximity to Mehta Pharmacy (1.2km away)",
        "Council brief: the Care specialist flags Dadi's mobility and prescription-delivery continuity as a hard constraint on any relocation timeline; the Finance specialist flags the buyback discount as a quantifiable loss",
      ],
      confidence: 0.71,
      consequenceIfWrong:
        "Relocating on a weak valuation loses irrecoverable equity; refusing and missing the deadline risks forced vacancy on worse terms. Either error is largely irreversible and affects every household member, including Dadi's care continuity.",
    },
  },

  // R2 — expired. Never silently rendered as approved: this is the case
  // spec §18.2 means by "approval expiry escalates; never auto-approves."
  {
    id: "approval-pta-signup-form",
    proposedActionSummary: "Submit Aarav's school PTA volunteer sign-up form for the October fair via the school portal.",
    riskTier: "R2",
    confidence: 0.8,
    consequenceIfWrong:
      "Submitting without explicit confirmation could commit Priya's time without her sign-off; letting the window lapse means Aarav's class may go unrepresented unless someone re-raises it by hand.",
    status: "expired",
    expiresAt: "2026-08-22T06:00:00Z",
    evidenceBundle: {
      proposedAction: "Submit Aarav's school PTA volunteer sign-up form for the October fair via the school portal.",
      reasoning:
        "The school's WhatsApp thread asked for parent volunteers by a fixed deadline, and no conflicting obligation was found for Priya on the fair date — but submitting a form on someone's behalf is R2 (requires approval), and no decision arrived before the window closed.",
      evidenceConsulted: [
        "School WhatsApp thread message, 21 Aug: requests parent volunteers by 22 Aug 6:00 AM IST",
        "Household calendar: no conflicting obligation for Priya on the fair date",
        "Approval window opened 21 Aug 09:00 IST, expired unactioned 22 Aug 06:00 IST",
      ],
      confidence: 0.8,
      consequenceIfWrong:
        "Submitting without explicit confirmation could commit Priya's time without her sign-off; letting the window lapse means Aarav's class may go unrepresented unless someone re-raises it by hand.",
    },
  },
] as const;

/**
 * DATA-LOADING BOUNDARY (Phase 5 seam, honestly documented per this
 * phase's brief).
 *
 * There is no live `/api/approvals`-style backend endpoint yet — Phase 6
 * ("Frontend Shell & Graph Visualisation") is where the app's real routing
 * and a general backend data-fetching pattern get designed, together, for
 * the first time (see `backend/app/main.py`, which today only exposes
 * `/health`, `/health/config`, a pubsub router, and a debug router — no
 * approvals endpoint exists to call). Inventing one unilaterally here
 * would be guessing at a contract E4 does not own.
 *
 * This function is the entire seam: it returns realistic fixture data
 * today, typed exactly as `ApprovalQueueItem[]` — the same shape a real
 * fetch would resolve to. Every component downstream (`ApprovalsBoard`,
 * `ApprovalQueue`, `EscalationSurface`, and their tests) depends only on
 * this function's return type, never on the fixture array itself. Swapping
 * the body for a real fetch against a real endpoint in Phase 6 is a
 * one-function change here, not a rewrite of any consumer.
 */
export function getApprovalQueue(): ApprovalQueueItem[] {
  return [...APPROVAL_QUEUE_FIXTURE];
}
