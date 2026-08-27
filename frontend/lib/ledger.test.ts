import { describe, expect, it } from "vitest";
import {
  computeRecoveredMoneySummary,
  getDisputePresentations,
  getLeakageCases,
  getPayrollResults,
  getReconciliationFindings,
  type LeakageCase,
} from "./ledger";

describe("getReconciliationFindings", () => {
  it("returns a fresh, independently-mutable array on every call", () => {
    const first = getReconciliationFindings();
    const second = getReconciliationFindings();
    expect(first).not.toBe(second);
    expect(first).toEqual(second);
  });

  it("includes at least one finding per Gate 7 checklist item", () => {
    const findings = getReconciliationFindings();
    const kinds = findings.map((f) => f.kind);
    expect(kinds).toContain("price_change"); // silent price hike
    expect(kinds).toContain("sms_ledger_mismatch"); // SMS/ledger mismatch -> dispute
    expect(kinds).toContain("salary_mismatch"); // salary mismatch -> dispute
    expect(kinds).toContain("salary_reconciled"); // the clean-match case
  });

  it("marks only genuine two-figure disagreements as requiring the dispute branch", () => {
    const requiresDispute = getReconciliationFindings().filter((f) => f.requiresDisputeBranch);
    expect(requiresDispute.map((f) => f.kind).sort()).toEqual(["salary_mismatch", "sms_ledger_mismatch"]);
  });

  it("ties the price-change finding to the real, live seeded commitment and event ids", () => {
    const priceChange = getReconciliationFindings().find((f) => f.kind === "price_change");
    expect(priceChange?.commitmentId).toBe("commitment-society-maintenance");
    expect(priceChange?.subjectEventIds).toContain("ledger-maintenance-debit");
  });
});

describe("getLeakageCases / computeRecoveredMoneySummary", () => {
  it("returns a fresh array on every call", () => {
    expect(getLeakageCases()).not.toBe(getLeakageCases());
  });

  it("has exactly three leakage-verdict cases, each with a drafted claim — spec's 'three claims drafted'", () => {
    const cases = getLeakageCases();
    const leakage = cases.filter((c) => c.finding.verdict === "leakage");
    expect(leakage).toHaveLength(3);
    expect(leakage.every((c) => c.recoveryDraft !== null)).toBe(true);
  });

  it("includes a worth_keeping and an ambiguous verdict, each with no draft", () => {
    const cases = getLeakageCases();
    const worthKeeping = cases.find((c) => c.finding.verdict === "worth_keeping");
    const ambiguous = cases.find((c) => c.finding.verdict === "ambiguous");
    expect(worthKeeping?.recoveryDraft).toBeNull();
    expect(ambiguous?.recoveryDraft).toBeNull();
  });

  it("computes a real, non-hardcoded annual leakage total: full amount for cancellations, hike-only for price adjustments", () => {
    const summary = computeRecoveredMoneySummary(getLeakageCases());
    // CloudTV (cancel, 499/mo) -> 5988; Fit Circle Gym (cancel, 1800/mo) ->
    // 21600; SpeedLink (price adjustment, hike of 500/mo) -> 6000.
    expect(summary.annualLeakageTotal).toBeCloseTo(5988 + 21600 + 6000, 5);
    expect(summary.draftsAwaitingApproval).toBe(3);
    expect(summary.leakageCaseCount).toBe(3);
    expect(summary.currency).toBe("INR");
  });

  it("counts only the price-hike amount, not the full bill, for a kept service", () => {
    const speedlink = getLeakageCases().find((c) => c.request.commitmentId === "commitment-speedlink-broadband");
    expect(speedlink?.recoveryDraft?.draftKind).toBe("price_adjustment_request");
    const onlyThisCase: LeakageCase[] = speedlink ? [speedlink] : [];
    const summary = computeRecoveredMoneySummary(onlyThisCase);
    // Full annual bill would be 1499*12=17988; only the 500/mo hike counts.
    expect(summary.annualLeakageTotal).toBeCloseTo(6000, 5);
  });

  it("falls back to the full annualised amount for a leakage case with no draft yet", () => {
    const undrafted: LeakageCase = {
      request: {
        commitmentId: "commitment-test",
        label: "Test",
        counterparty: "Test Vendor",
        amount: 100,
        cadence: "monthly",
        priceHistory: [],
        lastUsedAt: null,
        status: "active",
        householdPriorities: "",
        now: "2026-08-22T00:00:00Z",
      },
      finding: {
        commitmentId: "commitment-test",
        verdict: "leakage",
        reasoning: "test",
        daysSinceLastUsed: null,
        priceChangePct: null,
        confidence: 0.5,
        evidence: {},
      },
      recoveryDraft: null,
    };
    const summary = computeRecoveredMoneySummary([undrafted]);
    expect(summary.annualLeakageTotal).toBeCloseTo(1200, 5);
    expect(summary.draftsAwaitingApproval).toBe(0);
    expect(summary.leakageCaseCount).toBe(1);
  });

  it("ignores worth_keeping and ambiguous cases in the total entirely", () => {
    const cases = getLeakageCases().filter((c) => c.finding.verdict !== "leakage");
    const summary = computeRecoveredMoneySummary(cases);
    expect(summary.annualLeakageTotal).toBe(0);
    expect(summary.draftsAwaitingApproval).toBe(0);
  });
});

describe("getDisputePresentations", () => {
  it("returns a fresh array on every call", () => {
    expect(getDisputePresentations()).not.toBe(getDisputePresentations());
  });

  it("every dispute is pinned to human_resolution and has a non-zero discrepancy", () => {
    for (const dispute of getDisputePresentations()) {
      expect(dispute.escalatedTo).toBe("human_resolution");
      expect(dispute.discrepancyAmount).toBeGreaterThan(0);
      expect(dispute.discrepancyAmount).toBeCloseTo(Math.abs(dispute.figureA.amount - dispute.figureB.amount), 5);
    }
  });

  it("presents both figures with independent, real evidence — never a favoured side", () => {
    for (const dispute of getDisputePresentations()) {
      expect(dispute.figureA.evidenceText.length).toBeGreaterThan(0);
      expect(dispute.figureB.evidenceText.length).toBeGreaterThan(0);
      expect(dispute.figureA.sourceLabel).not.toBe(dispute.figureB.sourceLabel);
    }
  });
});

describe("getPayrollResults", () => {
  it("returns a fresh array on every call", () => {
    expect(getPayrollResults()).not.toBe(getPayrollResults());
  });

  it("includes both a clean (no-review) case and a needs-human-review case", () => {
    const results = getPayrollResults();
    expect(results.some((r) => !r.needsHumanReview && r.salary !== null)).toBe(true);
    expect(results.some((r) => r.needsHumanReview)).toBe(true);
  });

  it("never carries a computed salary figure alongside needs_human_review", () => {
    for (const result of getPayrollResults()) {
      if (result.needsHumanReview) {
        expect(result.salary).toBeNull();
      }
    }
  });

  it("every needs-human-review result names a review reason and at least one unresolved mark or a low-confidence record reason", () => {
    for (const result of getPayrollResults()) {
      if (result.needsHumanReview) {
        expect(result.reviewReason).not.toBeNull();
      }
    }
  });

  it("the clean case's net salary matches its own gross-minus-advances arithmetic", () => {
    const clean = getPayrollResults().find((r) => !r.needsHumanReview);
    const salary = clean?.salary;
    expect(salary).not.toBeNull();
    if (salary) {
      expect(salary.grossAmount).toBeCloseTo(salary.daysWorked * salary.dailyRate, 5);
      expect(salary.netSalaryDue).toBeCloseTo(salary.grossAmount - salary.totalAdvancesDeducted, 5);
    }
  });

  it("ties the clean case's real seeded ids consistently (register, obligation, advance)", () => {
    const clean = getPayrollResults().find((r) => !r.needsHumanReview);
    expect(clean?.registerImageRef).toBe("doc-attendance-register");
    expect(clean?.obligationNodeId).toBe("obligation-pay-maya-salary");
    expect(clean?.salary?.advanceEventIds).toContain("ledger-maya-advance");
  });
});
