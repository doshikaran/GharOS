import { describe, expect, it } from "vitest";
import { render, screen, renderHook } from "@testing-library/react";
import { getApprovalQueue } from "@/lib/approvals";
import { ApprovalsBoard } from "@/components/approvals/ApprovalsBoard";
import { useApprovalQueueCount } from "./useApprovalQueueCount";

// Same reference instant `ApprovalsBoard.test.tsx` uses — at this instant
// the fixture has exactly 2 items needing a decision (R2 call, R3 salary).
const NOW = new Date("2026-08-22T09:30:00Z");

describe("useApprovalQueueCount", () => {
  it("returns the pending count", () => {
    const { result } = renderHook(() => useApprovalQueueCount(NOW));
    expect(result.current).toBe(2);
  });

  it("agrees with /approvals's own rendered 'need your decision' count — same source, same predicate", () => {
    const { result } = renderHook(() => useApprovalQueueCount(NOW));

    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    const summary = screen.getByRole("status");

    // Pull the leading number out of "N need your decision · ...".
    const boardPendingCount = Number(summary.textContent?.match(/^(\d+) need your decision/)?.[1]);

    expect(boardPendingCount).toBeGreaterThan(0);
    expect(result.current).toBe(boardPendingCount);
  });

  it("excludes escalated (R4) and expired items from the count, same as needsApproval", () => {
    // Full fixture has 8 items: 2 pending, 2 escalated (1 R4 + 1 expired),
    // 4 resolved — the hook must report only the 2 pending, not all 8.
    const { result } = renderHook(() => useApprovalQueueCount(NOW));
    expect(result.current).toBeLessThan(getApprovalQueue().length);
  });
});
