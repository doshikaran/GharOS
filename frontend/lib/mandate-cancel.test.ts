import { describe, expect, it } from "vitest";
import { needsApproval } from "./approvals";
import { buildMandateCancelApprovalItem, mandateCancelApprovalId } from "./mandate-cancel";
import type { LedgerCommitmentRow } from "./ledger-transactions";

const NOW = new Date("2026-08-22T09:00:00Z");

const commitment: LedgerCommitmentRow = {
  id: "commitment-society-maintenance",
  label: "Sunrise Society maintenance",
  counterparty: "Sunrise Apartments Society",
  amount: 2500,
  cadence: "monthly",
  priceHistory: [
    ["2025-08-22T09:00:00Z", 2300],
    ["2026-07-23T09:00:00Z", 2500],
  ],
  lastUsedAt: "2026-07-23T09:00:00Z",
  status: "active",
  derivation: "extracted",
  confidence: 0.9,
};

describe("buildMandateCancelApprovalItem", () => {
  it("builds an R3 pending approval item, 'Cancel mandate' is spec's own R3 example", () => {
    const item = buildMandateCancelApprovalItem(commitment, NOW);
    expect(item.riskTier).toBe("R3");
    expect(item.status).toBe("pending");
    expect(needsApproval(item, NOW)).toBe(true);
  });

  it("derives the item id deterministically from the live commitment id", () => {
    const item = buildMandateCancelApprovalItem(commitment, NOW);
    expect(item.id).toBe(mandateCancelApprovalId(commitment.id));
    expect(item.id).toContain(commitment.id);
  });

  it("names the real commitment id, label, and amount in the proposed action and reasoning", () => {
    const item = buildMandateCancelApprovalItem(commitment, NOW);
    expect(item.proposedActionSummary).toContain("Sunrise Society maintenance");
    expect(item.proposedActionSummary).toContain("Sunrise Apartments Society");
    expect(item.evidenceBundle.reasoning).toContain(commitment.id);
  });

  it("carries a full evidence bundle, never a bare action with no reasoning", () => {
    const item = buildMandateCancelApprovalItem(commitment, NOW);
    expect(item.evidenceBundle.evidenceConsulted.length).toBeGreaterThan(0);
    expect(item.evidenceBundle.consequenceIfWrong.length).toBeGreaterThan(0);
    expect(item.evidenceBundle.confidence).toBeGreaterThan(0);
  });

  it("describes 'no recorded usage' honestly when lastUsedAt is null", () => {
    const neverUsed: LedgerCommitmentRow = { ...commitment, lastUsedAt: null };
    const item = buildMandateCancelApprovalItem(neverUsed, NOW);
    expect(item.evidenceBundle.reasoning).toContain("no recorded usage");
  });

  it("sets an expiry in the future, never already expired", () => {
    const item = buildMandateCancelApprovalItem(commitment, NOW);
    expect(new Date(item.expiresAt).getTime()).toBeGreaterThan(NOW.getTime());
  });
});
