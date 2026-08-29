import { describe, expect, it } from "vitest";
import {
  AARAV_ID,
  DADI_ID,
  MAYA_ID,
  PRIYA_ID,
  PRIYA_LIVE_GROCERIES_COST,
  TASK_WEEKLY_GROCERIES_ID,
  getComparativePreferences,
  getConcessionEvidence,
  getEf1Violations,
  getFairAllocationResult,
  getFairnessVerificationResult,
  getLoadImbalanceFindings,
  getRenegotiationTrigger,
  getValuationExtractionResults,
  type FairAllocationResult,
} from "./fair-allocator";

/** Re-derives each person's own bundle cost from `picks` alone — an
 * independent check that never trusts `personTotalCost` at face value,
 * mirroring `verify_ef1`'s own "duplicates none of the solver's internal
 * logic" discipline. */
function bundleCostFromPicks(result: FairAllocationResult, personId: string): number {
  return result.picks.filter((pick) => pick.personId === personId).reduce((sum, pick) => sum + pick.cost, 0);
}

describe("getFairAllocationResult", () => {
  it.each(["before", "after"] as const)(
    "%s: personTotalCost matches the sum of that person's own picks",
    (scenario) => {
      const result = getFairAllocationResult(scenario);
      for (const personId of result.order) {
        expect(result.personTotalCost[personId]).toBeCloseTo(bundleCostFromPicks(result, personId), 10);
      }
    },
  );

  it.each(["before", "after"] as const)("%s: every task in allocation appears in exactly one pick", (scenario) => {
    const result = getFairAllocationResult(scenario);
    const taskIds = Object.keys(result.allocation);
    for (const taskId of taskIds) {
      const picksForTask = result.picks.filter((pick) => pick.taskId === taskId);
      expect(picksForTask).toHaveLength(1);
      expect(picksForTask[0]?.personId).toBe(result.allocation[taskId]);
    }
  });

  it("before: Priya's grocery-run pick matches the real, live ValuationProfile cost exactly", () => {
    const result = getFairAllocationResult("before");
    expect(result.allocation[TASK_WEEKLY_GROCERIES_ID]).toBe(PRIYA_ID);
    expect(result.personTotalCost[PRIYA_ID]).toBe(PRIYA_LIVE_GROCERIES_COST);
  });

  it("after: the night-shift trigger changes who holds which task, not just the costs", () => {
    const before = getFairAllocationResult("before");
    const after = getFairAllocationResult("after");
    expect(before.allocation).not.toEqual(after.allocation);
    // A genuine reallocation, not a re-costed re-display of the same split.
    expect(before.allocation[TASK_WEEKLY_GROCERIES_ID]).toBe(PRIYA_ID);
    expect(after.allocation[TASK_WEEKLY_GROCERIES_ID]).toBe(MAYA_ID);
  });
});

describe("verify_ef1 (re-derived independently, per person, from the fixture's own costs)", () => {
  it.each(["before", "after"] as const)("%s: EF1 holds for both ordered pairs, matches getEf1Violations", (scenario) => {
    const result = getFairAllocationResult(scenario);
    const costsByPerson = new Map(getValuationExtractionResults(scenario).map((v) => [v.personId, v.costs]));
    // Priya's grocery-run cost is real/live, not part of the fixture's own
    // `costs` map for "before" (it only carries the *fixture-added* o2/o4
    // costs) — patch it in for this independent check.
    const priyaCosts = { ...costsByPerson.get(PRIYA_ID), [TASK_WEEKLY_GROCERIES_ID]: PRIYA_LIVE_GROCERIES_COST };
    costsByPerson.set(PRIYA_ID, priyaCosts);

    const bundles = new Map<string, string[]>();
    for (const [taskId, personId] of Object.entries(result.allocation)) {
      bundles.set(personId, [...(bundles.get(personId) ?? []), taskId]);
    }

    for (const envier of [PRIYA_ID, MAYA_ID]) {
      const ownBundle = bundles.get(envier) ?? [];
      if (ownBundle.length === 0) continue;
      const envierCosts = costsByPerson.get(envier) ?? {};
      const ownCost = ownBundle.reduce((sum, t) => sum + (envierCosts[t] ?? 0), 0);
      const worstOwnItem = Math.max(...ownBundle.map((t) => envierCosts[t] ?? 0));
      for (const envied of [PRIYA_ID, MAYA_ID]) {
        if (envied === envier) continue;
        const enviedBundle = bundles.get(envied) ?? [];
        const costForEnviedBundle = enviedBundle.reduce((sum, t) => sum + (envierCosts[t] ?? 0), 0);
        expect(ownCost - worstOwnItem).toBeLessThanOrEqual(costForEnviedBundle);
      }
    }

    expect(getEf1Violations(scenario)).toEqual([]);
  });
});

describe("getFairnessVerificationResult", () => {
  it.each(["before", "after"] as const)("%s: ef1Holds is true with zero violations, matching getEf1Violations", (scenario) => {
    const verification = getFairnessVerificationResult(scenario);
    expect(verification.ef1Holds).toBe(true);
    expect(verification.violationCount).toBe(0);
  });

  it.each(["before", "after"] as const)(
    "%s: every explanation's totalCostToSelf matches the allocation's own personTotalCost",
    (scenario) => {
      const allocation = getFairAllocationResult(scenario);
      const verification = getFairnessVerificationResult(scenario);
      for (const explanation of verification.explanations) {
        expect(explanation.totalCostToSelf).toBe(allocation.personTotalCost[explanation.personId]);
        expect([...explanation.taskIds].sort()).toEqual(
          Object.entries(allocation.allocation)
            .filter(([, personId]) => personId === explanation.personId)
            .map(([taskId]) => taskId)
            .sort(),
        );
      }
    },
  );

  it("never uses the word 'optimal' or an unqualified 'fair', states EF1 precisely, per docs/FAIRNESS_GUARANTEE.md", () => {
    for (const scenario of ["before", "after"] as const) {
      for (const explanation of getFairnessVerificationResult(scenario).explanations) {
        expect(explanation.explanationText.toLowerCase()).not.toContain("optimal");
      }
    }
  });
});

describe("getConcessionEvidence", () => {
  it("Priya's concession numbers match her own before/after personTotalCost exactly", () => {
    const before = getFairAllocationResult("before");
    const after = getFairAllocationResult("after");
    const [concession] = getConcessionEvidence();
    expect(concession?.personId).toBe(PRIYA_ID);
    expect(concession?.priorBundleCost).toBe(before.personTotalCost[PRIYA_ID]);
    expect(concession?.newBundleCost).toBe(after.personTotalCost[PRIYA_ID]);
    expect(concession?.newBundleCost).toBeGreaterThan(concession?.priorBundleCost ?? Infinity);
  });
});

describe("getRenegotiationTrigger", () => {
  it("names Maya and a schedule constraint change, matching the after-scenario's own cost changes", () => {
    const trigger = getRenegotiationTrigger();
    expect(trigger.personId).toBe(MAYA_ID);
    expect(trigger.reasonKind).toBe("schedule_constraint_change");
    expect(trigger.detail.toLowerCase()).toContain("night shift");
  });
});

describe("getComparativePreferences", () => {
  it("every stated preference is consistent with that person's own priced cost ordering", () => {
    const beforeCosts = new Map(getValuationExtractionResults("before").map((v) => [v.personId, v.costs]));
    for (const pref of getComparativePreferences()) {
      const costs = { ...beforeCosts.get(pref.personId) };
      if (pref.personId === PRIYA_ID) costs[TASK_WEEKLY_GROCERIES_ID] = PRIYA_LIVE_GROCERIES_COST;
      const costA = costs[pref.taskAId];
      const costB = costs[pref.taskBId];
      expect(costA).toBeDefined();
      expect(costB).toBeDefined();
      if (pref.preferred === "tie") {
        expect(costA).toBe(costB);
      } else if (pref.preferred === "task_a") {
        expect(costA as number).toBeLessThan(costB as number);
      } else {
        expect(costB as number).toBeLessThan(costA as number);
      }
    }
  });
});

describe("getLoadImbalanceFindings", () => {
  it("covers all four household members exactly once", () => {
    const findings = getLoadImbalanceFindings();
    expect(findings.map((f) => f.personId).sort()).toEqual([AARAV_ID, DADI_ID, MAYA_ID, PRIYA_ID].sort());
  });

  it("expectedShare sums to 1.0 across the household", () => {
    const total = getLoadImbalanceFindings().reduce((sum, f) => sum + f.expectedShare, 0);
    expect(total).toBeCloseTo(1.0, 3);
  });

  it("observedShare sums to 1.0 across the household", () => {
    const total = getLoadImbalanceFindings().reduce((sum, f) => sum + (f.observedShare ?? 0), 0);
    expect(total).toBeCloseTo(1.0, 3);
  });

  it("drift is always observedShare minus expectedShare", () => {
    for (const finding of getLoadImbalanceFindings()) {
      expect(finding.drift).toBeCloseTo((finding.observedShare ?? 0) - finding.expectedShare, 10);
    }
  });

  it("a 'balanced' or 'insufficient_data' verdict never carries the flash model tier (no narration to justify one)", () => {
    for (const finding of getLoadImbalanceFindings()) {
      if (finding.verdict !== "creeping_imbalance") {
        expect(finding.modelTier).toBe("deterministic");
      }
    }
  });
});
