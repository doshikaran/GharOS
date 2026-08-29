/**
 * Builds a real `ApprovalQueueItem` proposing to cancel a live
 * `RECURRING_COMMITMENT` (PHASES.md Phase 7 demo beat — "a live
 * silent-mandate kill... show the approval gate").
 *
 * Routes through the exact same `components/approvals/` flow Phase 5
 * built (`ApprovalsBoard`'s `extraItems` prop) rather than a parallel
 * approval surface. Risk tier is `R3` per `RISK_TIER_POLICY` — "Cancel
 * mandate" is spec §18.1's own literal R3 example — and this mirrors
 * exactly the `effect: "cancel_mandate"` shape
 * `backend/app/arbitration/payment_tool.py`'s real `SandboxPaymentTool`
 * would execute once approved: `commitment_id` here is this item's live,
 * real graph node id, never a fixture one, because the input to this
 * function is always a `LedgerCommitmentRow` read out of the live
 * `/graph/snapshot` response.
 *
 * Approving this item inside `ApprovalsBoard` only flips its local status
 * to `"approved"` — the same true-for-every-item Phase 5 behaviour, since
 * no live approval-execution endpoint exists yet either (see
 * `lib/approvals.ts`'s own data-loading-boundary comment). This function
 * never claims to call `SandboxPaymentTool` itself.
 */

import type { ApprovalQueueItem, EvidenceBundle } from "./approvals";
import type { LedgerCommitmentRow } from "./ledger-transactions";

const MANDATE_CANCEL_APPROVAL_WINDOW_HOURS = 24;

/** Every mandate-cancel proposal's id is derived deterministically from the
 * live commitment id, so a caller can tell whether a given commitment
 * already has a pending proposal without tracking separate state. */
export const MANDATE_CANCEL_ID_PREFIX = "mandate-cancel-";

export function mandateCancelApprovalId(commitmentId: string): string {
  return `${MANDATE_CANCEL_ID_PREFIX}${commitmentId}`;
}

function formatRupees(amount: number): string {
  return `₹${amount.toLocaleString("en-IN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function describeUsage(lastUsedAt: string | null, now: Date): string {
  if (lastUsedAt === null) return "no recorded usage on file at all";
  const ms = now.getTime() - new Date(lastUsedAt).getTime();
  const days = Math.max(0, Math.floor(ms / (24 * 60 * 60 * 1000)));
  return `last used ${days} day${days === 1 ? "" : "s"} ago`;
}

/**
 * Builds the `ApprovalQueueItem` for cancelling `commitment` — a real,
 * live `RECURRING_COMMITMENT` read from `/graph/snapshot`, not fixture
 * data. `now` is injectable for deterministic tests.
 */
export function buildMandateCancelApprovalItem(
  commitment: LedgerCommitmentRow,
  now: Date = new Date(),
): ApprovalQueueItem {
  const usage = describeUsage(commitment.lastUsedAt, now);
  const proposedActionSummary = `Cancel the recurring mandate for ${commitment.label} (${commitment.counterparty}), ${formatRupees(commitment.amount)}/${commitment.cadence}.`;
  const reasoning =
    `This mandate is live in the household graph as ${commitment.id}, ${usage}. Cancelling a mandate is a real, ` +
    "irreversible-until-re-established action, so it goes through the same approval gate every payment/mandate " +
    'action does (spec §10.5\'s payment-tool group; "Cancel mandate" is R3 per spec §18.1). Approving this ' +
    "authorises the exact effect=\"cancel_mandate\" call `SandboxPaymentTool` would perform against this " +
    "commitment's real node id.";
  const consequenceIfWrong =
    `Cancelling a mandate still in genuine use interrupts ${commitment.counterparty}'s service until a household ` +
    "member re-establishes it by hand. The underlying payment tool is sandboxed, no real external payment rail is " +
    "ever called, but the graph's own mandate-status record would still need a manual correction.";
  const evidenceConsulted = [
    `Live RECURRING_COMMITMENT node ${commitment.id}: "${commitment.label}", ${formatRupees(commitment.amount)}/${commitment.cadence}, status "${commitment.status}".`,
    `Usage signal: ${usage}.`,
    commitment.priceHistory.length > 0
      ? `Price history on file: ${commitment.priceHistory.length} recorded point(s), most recent ${formatRupees(commitment.priceHistory[commitment.priceHistory.length - 1][1])}.`
      : "No price history recorded for this commitment.",
  ];
  const confidence = 0.8;
  const expiresAt = new Date(now.getTime() + MANDATE_CANCEL_APPROVAL_WINDOW_HOURS * 60 * 60 * 1000).toISOString();

  const evidenceBundle: EvidenceBundle = {
    proposedAction: proposedActionSummary,
    reasoning,
    evidenceConsulted,
    confidence,
    consequenceIfWrong,
  };

  return {
    id: mandateCancelApprovalId(commitment.id),
    proposedActionSummary,
    riskTier: "R3",
    confidence,
    consequenceIfWrong,
    status: "pending",
    expiresAt,
    evidenceBundle,
  };
}
