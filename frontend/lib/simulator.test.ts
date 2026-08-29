import { describe, expect, it } from "vitest";
import {
  MIN_SAMPLE_SIZE_FOR_CALIBRATION,
  answerFollowup,
  buildRiskRegister,
  getBackwardModeAnalysis,
  getBranchCritiques,
  getBranchProjections,
  getCalibrationEstimate,
  getDecisionBrief,
  getDecisionFrame,
  getGroundingResults,
} from "./simulator";

describe("getDecisionFrame", () => {
  it("flags the seeded decision as a false binary and names an unconsidered option", () => {
    const frame = getDecisionFrame();
    expect(frame.isFalseBinary).toBe(true);
    expect(frame.unconsideredOptions.length).toBeGreaterThan(0);
  });

  it("proposes 2-4 branch labels, per this phase's brief", () => {
    const frame = getDecisionFrame();
    expect(frame.proposedBranchLabels.length).toBeGreaterThanOrEqual(2);
    expect(frame.proposedBranchLabels.length).toBeLessThanOrEqual(4);
  });
});

describe("fixture cross-consistency", () => {
  it("every BranchProjection.branchId has a matching label in DecisionFrame.proposedBranchLabels", () => {
    const frame = getDecisionFrame();
    const projections = getBranchProjections();
    for (const projection of projections) {
      expect(frame.proposedBranchLabels).toContain(projection.label);
    }
  });

  it("every BranchCritique.branchId matches a real BranchProjection.branchId in the same fixture set", () => {
    const projections = getBranchProjections();
    const projectionIds = new Set(projections.map((p) => p.branchId));
    const critiques = getBranchCritiques();
    expect(critiques.length).toBeGreaterThan(0);
    for (const critique of critiques) {
      expect(projectionIds.has(critique.branchId)).toBe(true);
    }
  });

  it("every GroundingResult.branchLabel matches a real BranchProjection.label", () => {
    const projections = getBranchProjections();
    const labels = new Set(projections.map((p) => p.label));
    const groundingResults = getGroundingResults();
    expect(groundingResults.length).toBeGreaterThan(0);
    for (const result of groundingResults) {
      expect(labels.has(result.branchLabel)).toBe(true);
    }
  });

  it("a branch with groundingRefs always has a matching GroundingResult with at least one citation", () => {
    const projections = getBranchProjections();
    const groundingResults = getGroundingResults();
    const resultByLabel = new Map(groundingResults.map((r) => [r.branchLabel, r]));

    for (const projection of projections) {
      const result = resultByLabel.get(projection.label);
      expect(result).toBeDefined();
      if (projection.groundingRefs.length > 0) {
        expect(result!.citations.length).toBeGreaterThan(0);
      }
    }
  });

  it("a branch with zero groundingRefs has a GroundingResult with zero citations, never a dangling ref nor a fabricated one", () => {
    const projections = getBranchProjections();
    const groundingResults = getGroundingResults();
    const resultByLabel = new Map(groundingResults.map((r) => [r.branchLabel, r]));
    const emptyRefBranches = projections.filter((p) => p.groundingRefs.length === 0);

    expect(emptyRefBranches.length).toBeGreaterThan(0);
    for (const projection of emptyRefBranches) {
      expect(resultByLabel.get(projection.label)!.citations).toHaveLength(0);
    }
  });

  it("DecisionBrief.decisionId matches DecisionFrame.decisionId", () => {
    expect(getDecisionBrief().decisionId).toBe(getDecisionFrame().decisionId);
  });

  it("DecisionBrief has one branchSummary per proposed branch", () => {
    const frame = getDecisionFrame();
    const brief = getDecisionBrief();
    expect(brief.branchSummaries.length).toBe(frame.proposedBranchLabels.length);
  });
});

describe("DecisionBrief never states a recommendation or verdict", () => {
  const VERDICT_WORDS = ["recommend", "verdict", "best choice", "should choose", "optimal", "you should"];

  it("has no recommendedBranchId or verdict-shaped field on the type", () => {
    const brief = getDecisionBrief();
    expect(Object.keys(brief)).not.toContain("recommendedBranchId");
    expect(Object.keys(brief)).not.toContain("verdict");
  });

  it("never states a recommendation in branchSummaries, tradeOffs, or openQuestions text", () => {
    const brief = getDecisionBrief();
    const allText = [...brief.branchSummaries, ...brief.tradeOffs, ...brief.openQuestions].join(" ").toLowerCase();
    for (const word of VERDICT_WORDS) {
      expect(allText).not.toContain(word);
    }
  });

  it("never states a recommendation anywhere in the backward-mode analysis either", () => {
    const analysis = getBackwardModeAnalysis();
    const allText = [
      analysis.planDescription,
      analysis.assumedFailurePoint,
      analysis.confidenceNote,
      ...analysis.suggestedMitigations,
    ]
      .join(" ")
      .toLowerCase();
    for (const word of VERDICT_WORDS) {
      expect(allText).not.toContain(word);
    }
  });
});

describe("buildRiskRegister", () => {
  it("flattens every branch's over-optimistic claims and omitted effects into a flat list", () => {
    const projections = getBranchProjections();
    const critiques = getBranchCritiques();
    const register = buildRiskRegister(critiques, projections);

    const expectedCount = critiques.reduce(
      (sum, c) => sum + c.overOptimisticClaims.length + c.omittedSecondOrderEffects.length,
      0,
    );
    expect(register.length).toBe(expectedCount);
  });

  it("every entry carries a resolved branchLabel, never a dangling id", () => {
    const projections = getBranchProjections();
    const critiques = getBranchCritiques();
    const register = buildRiskRegister(critiques, projections);
    const validLabels = new Set(projections.map((p) => p.label));
    for (const entry of register) {
      expect(validLabels.has(entry.branchLabel)).toBe(true);
    }
  });

  it("skips a critique whose branchId has no matching projection, rather than rendering a dangling label", () => {
    const projections = getBranchProjections();
    const orphanCritique = {
      branchId: "branch-does-not-exist",
      overOptimisticClaims: ["should never appear"],
      omittedSecondOrderEffects: [],
      revisedConfidenceNote: "n/a",
    };
    const register = buildRiskRegister([orphanCritique], projections);
    expect(register).toHaveLength(0);
  });

  it("categorises entries distinctly as over-optimistic claim vs omitted second-order effect", () => {
    const projections = getBranchProjections();
    const critiques = getBranchCritiques();
    const register = buildRiskRegister(critiques, projections);
    const categories = new Set(register.map((e) => e.category));
    expect(categories.has("over-optimistic claim")).toBe(true);
    expect(categories.has("omitted second-order effect")).toBe(true);
  });
});

describe("CalibrationEstimate, thin history vs real variance", () => {
  it("uses MIN_SAMPLE_SIZE_FOR_CALIBRATION = 3, the same threshold as Phase 9's Slippage Analyst", () => {
    expect(MIN_SAMPLE_SIZE_FOR_CALIBRATION).toBe(3);
  });

  it("renders the thin-history case honestly: below threshold, no numeric mean/stdev is fabricated", () => {
    const estimate = getCalibrationEstimate("relocation");
    expect(estimate).toBeDefined();
    expect(estimate!.sampleSize).toBeLessThan(MIN_SAMPLE_SIZE_FOR_CALIBRATION);
    expect(estimate!.isThinHistory).toBe(true);
    expect(estimate!.meanVariance).toBeNull();
    expect(estimate!.stdevVariance).toBeNull();
    expect(estimate!.honestNote.length).toBeGreaterThan(0);
  });

  it("renders real variance once sample size clears the threshold", () => {
    const estimate = getCalibrationEstimate("staff_transition");
    expect(estimate).toBeDefined();
    expect(estimate!.sampleSize).toBeGreaterThanOrEqual(MIN_SAMPLE_SIZE_FOR_CALIBRATION);
    expect(estimate!.isThinHistory).toBe(false);
    expect(estimate!.meanVariance).not.toBeNull();
    expect(estimate!.stdevVariance).not.toBeNull();
    expect(estimate!.confidenceBandNote).not.toBeNull();
  });

  it("returns undefined for a category with no history on file, rather than a fabricated zero estimate", () => {
    expect(getCalibrationEstimate("some-unknown-category")).toBeUndefined();
  });
});

describe("BackwardModeAnalysis", () => {
  it("names a plan, an assumed failure point, and at least one supporting outcome id", () => {
    const analysis = getBackwardModeAnalysis();
    expect(analysis.planDescription.length).toBeGreaterThan(0);
    expect(analysis.assumedFailurePoint.length).toBeGreaterThan(0);
    expect(analysis.supportingOutcomeIds.length).toBeGreaterThan(0);
  });

  it("suggests at least one concrete mitigation", () => {
    expect(getBackwardModeAnalysis().suggestedMitigations.length).toBeGreaterThan(0);
  });
});

describe("answerFollowup", () => {
  it("surfaces a matching open question verbatim when the question overlaps it", () => {
    const brief = getDecisionBrief();
    const answer = answerFollowup(brief, "What about the dialysis centre confirming a slot?");
    expect(answer).toContain("Mehta Dialysis Centre");
    expect(answer.toLowerCase()).toContain("open question");
  });

  it("surfaces a matching trade-off when no open question overlaps as closely", () => {
    const brief = getDecisionBrief();
    const answer = answerFollowup(brief, "How does speed compare against continuity of care?");
    expect(answer.toLowerCase()).toContain("trade-off");
  });

  it("falls back honestly when nothing in the brief matches the question", () => {
    const brief = getDecisionBrief();
    const answer = answerFollowup(brief, "What is the household's favourite colour?");
    expect(answer).toContain("isn't something the Simulator answers with a single figure");
  });

  it("is deterministic, same brief and question always produce the same answer", () => {
    const brief = getDecisionBrief();
    const first = answerFollowup(brief, "Tell me about the school continuity form");
    const second = answerFollowup(brief, "Tell me about the school continuity form");
    expect(first).toBe(second);
  });

  it("never returns a verdict, even when asked directly which branch is best", () => {
    const brief = getDecisionBrief();
    const answer = answerFollowup(brief, "Which branch is the best choice overall?");
    expect(answer.toLowerCase()).not.toContain("you should choose");
    expect(answer.toLowerCase()).not.toContain("the best branch is");
  });
});
