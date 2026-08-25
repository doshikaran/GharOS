import { describe, expect, it } from "vitest";
import {
  RISK_TIER_ORDER,
  RISK_TIER_POLICY,
  formatDateTime,
  getApprovalQueue,
  isEscalation,
  isExpired,
  isResolved,
  needsApproval,
  type ApprovalQueueItem,
  type RiskTier,
} from "./approvals";

describe("RISK_TIER_POLICY", () => {
  it("defines a policy entry for every RiskTier value, matching spec §18.1", () => {
    for (const tier of RISK_TIER_ORDER) {
      const entry = RISK_TIER_POLICY[tier];
      expect(entry.tier).toBe(tier);
      expect(entry.label.startsWith(tier)).toBe(true);
      expect(entry.definition.length).toBeGreaterThan(0);
      expect(entry.policy.length).toBeGreaterThan(0);
      expect(entry.examples.length).toBeGreaterThan(0);
    }
  });

  it("marks R4 as never auto-executing, and only R4, in its policy text", () => {
    expect(RISK_TIER_POLICY.R4.policy).toMatch(/never auto-execute/i);
    const others: RiskTier[] = ["R0", "R1", "R2", "R3"];
    for (const tier of others) {
      expect(RISK_TIER_POLICY[tier].policy).not.toMatch(/never auto-execute/i);
    }
  });
});

describe("getApprovalQueue fixture", () => {
  const items = getApprovalQueue();

  it("returns a fresh array each call (never a shared mutable reference)", () => {
    expect(getApprovalQueue()).not.toBe(getApprovalQueue());
    expect(getApprovalQueue()).toEqual(items);
  });

  it("includes at least one example of every RiskTier value", () => {
    const tiers = new Set(items.map((item) => item.riskTier));
    for (const tier of RISK_TIER_ORDER) {
      expect(tiers.has(tier)).toBe(true);
    }
  });

  it("includes at least one EXPIRED case", () => {
    expect(items.some((item) => item.status === "expired")).toBe(true);
  });

  it("gives every item a fully populated evidence bundle — nothing truncated or omitted", () => {
    for (const item of items) {
      expect(item.evidenceBundle.proposedAction.length).toBeGreaterThan(0);
      expect(item.evidenceBundle.reasoning.length).toBeGreaterThan(0);
      expect(item.evidenceBundle.evidenceConsulted.length).toBeGreaterThan(0);
      expect(item.evidenceBundle.confidence).toBeGreaterThanOrEqual(0);
      expect(item.evidenceBundle.confidence).toBeLessThanOrEqual(1);
      expect(item.evidenceBundle.consequenceIfWrong.length).toBeGreaterThan(0);
    }
  });

  it("never mentions the word 'debate' anywhere in the fixture copy (safety invariant #6)", () => {
    const haystack = JSON.stringify(items).toLowerCase();
    expect(haystack).not.toContain("debate");
  });
});

describe("isExpired", () => {
  const pendingItem: ApprovalQueueItem = {
    id: "test-pending",
    proposedActionSummary: "Test action",
    riskTier: "R2",
    confidence: 0.9,
    consequenceIfWrong: "Test consequence",
    status: "pending",
    expiresAt: "2026-08-22T12:00:00Z",
    evidenceBundle: {
      proposedAction: "Test action",
      reasoning: "Test reasoning",
      evidenceConsulted: ["Test evidence"],
      confidence: 0.9,
      consequenceIfWrong: "Test consequence",
    },
  };

  it("is false for a pending item well before its expiry", () => {
    expect(isExpired(pendingItem, new Date("2026-08-22T10:00:00Z"))).toBe(false);
  });

  it("is true for an item explicitly flagged 'expired' by status, regardless of now", () => {
    const expiredItem: ApprovalQueueItem = { ...pendingItem, status: "expired" };
    expect(isExpired(expiredItem, new Date("2000-01-01T00:00:00Z"))).toBe(true);
  });

  it("defensively treats a still-'pending' item past its own expiresAt as expired", () => {
    expect(isExpired(pendingItem, new Date("2026-08-22T12:00:01Z"))).toBe(true);
  });

  it("never treats an approved item as expired even if its expiresAt has passed", () => {
    const approvedItem: ApprovalQueueItem = { ...pendingItem, status: "approved" };
    expect(isExpired(approvedItem, new Date("2099-01-01T00:00:00Z"))).toBe(false);
  });
});

describe("needsApproval / isEscalation / isResolved partition every fixture item exactly once", () => {
  const items = getApprovalQueue();
  const now = new Date("2026-08-22T09:30:00Z");

  it("assigns each item to exactly one of the three categories", () => {
    for (const item of items) {
      const flags = [needsApproval(item, now), isEscalation(item, now), isResolved(item, now)];
      expect(flags.filter(Boolean)).toHaveLength(1);
    }
  });

  it("never lets an R4 item need approval — the Council never resolves it (spec §18.2)", () => {
    for (const item of items.filter((i) => i.riskTier === "R4")) {
      expect(needsApproval(item, now)).toBe(false);
      expect(isEscalation(item, now)).toBe(true);
    }
  });

  it("routes the expired item to escalation, never to resolved or needs-approval", () => {
    const expiredItem = items.find((item) => item.status === "expired");
    expect(expiredItem).toBeDefined();
    if (!expiredItem) return;
    expect(isEscalation(expiredItem, now)).toBe(true);
    expect(needsApproval(expiredItem, now)).toBe(false);
    expect(isResolved(expiredItem, now)).toBe(false);
  });

  it("routes approved/rejected non-R4 items to resolved, not to needs-approval", () => {
    const resolvedCandidates = items.filter(
      (item) => item.riskTier !== "R4" && (item.status === "approved" || item.status === "rejected"),
    );
    expect(resolvedCandidates.length).toBeGreaterThan(0);
    for (const item of resolvedCandidates) {
      expect(isResolved(item, now)).toBe(true);
      expect(needsApproval(item, now)).toBe(false);
    }
  });
});

describe("formatDateTime", () => {
  it("renders a real, human-readable date/time rather than the raw ISO string", () => {
    const formatted = formatDateTime("2026-08-22T11:00:00Z");
    expect(formatted).not.toBe("2026-08-22T11:00:00Z");
    expect(formatted.length).toBeGreaterThan(0);
  });
});
