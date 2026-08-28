"use client";

import { useMemo } from "react";
import { getApprovalQueue, needsApproval, type ApprovalQueueItem } from "@/lib/approvals";

/**
 * The live pending-approval count shown as a badge on the sidebar's
 * "Approvals" nav item (ADR-018) — sourced from exactly the same data and
 * the exact same predicate `/approvals` itself uses for its own "N need
 * your decision" summary (`ApprovalsBoard`'s `pendingCount`), never a
 * second, divergent source of truth.
 *
 * `/approvals`'s current fetch logic (spec §18.2 seam, documented in
 * `lib/approvals.ts`) is `getApprovalQueue()` — a synchronous fixture
 * function typed exactly as a real `/api/approvals`-style fetch would
 * eventually resolve, per that file's own "DATA-LOADING BOUNDARY" comment.
 * There is no live backend endpoint yet (that seam is still open, as
 * documented there) — this hook reads the identical function rather than
 * inventing a second path (e.g. re-deriving from `/graph/snapshot`), so
 * the day that seam closes, both `/approvals` and this hook pick up the
 * real data in the same single-function change.
 *
 * "Pending" here means exactly `needsApproval` — below R4, still
 * `pending`, not expired. An expired or R4 item is an escalation, not a
 * pending decision, and is deliberately excluded from this count for the
 * same reason `ApprovalQueue` excludes it from its own "needs your
 * decision" section.
 */
export function useApprovalQueueCount(now?: Date): number {
  return useMemo(() => {
    const clock = now ?? new Date();
    const items: readonly ApprovalQueueItem[] = getApprovalQueue();
    return items.filter((item) => needsApproval(item, clock)).length;
  }, [now]);
}
