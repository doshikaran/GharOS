import { describe, expect, it } from "vitest";
import {
  AARAV_ID,
  BLOCKER_TYPES,
  DADI_ID,
  DADI_NAP_CONSTRAINT_ID,
  MAYA_ID,
  PRIYA_ID,
  applyDiagnosisCorrection,
  buildDadiPhysioWindowResult,
  extractBlockerTypeFromPattern,
  findMatchingPattern,
  getDadiPhysioCandidates,
  getDadiPhysioDiagnosis,
  getDadiPhysioFixtureConstraints,
  getDentalCheckupAttempts,
  getDentalCheckupCurrentDiagnosis,
  getDentalCheckupModalitySwitch,
  getDentalCheckupSlippageAnalysis,
  getDentalCheckupWindow,
  getEyeCheckupDiagnosis,
  getEyeCheckupInformationFetch,
  getFieldTripDecisionNarrowing,
  getFieldTripDiagnosis,
  getInitialFrictionPatterns,
  getStaleObligationDetection,
  patternConfidence,
  patternsForPerson,
  type DiagnosisCorrection,
} from "./intention-action";
import { personAvailabilityForWindow } from "./schedule-availability";

describe("BLOCKER_TYPES", () => {
  it("is exactly the six-type taxonomy, no more, no fewer", () => {
    expect(BLOCKER_TYPES).toHaveLength(6);
    expect(new Set(BLOCKER_TYPES).size).toBe(6);
  });
});

describe("patternConfidence", () => {
  it("grows with support count but never exceeds the max", () => {
    expect(patternConfidence(0)).toBeCloseTo(0.5);
    expect(patternConfidence(1)).toBeCloseTo(0.6);
    expect(patternConfidence(3)).toBeCloseTo(0.8);
    expect(patternConfidence(50)).toBeCloseTo(0.9);
  });
});

describe("extractBlockerTypeFromPattern", () => {
  it("recovers the blocker type from a real friction-pattern description", () => {
    const patterns = getInitialFrictionPatterns();
    expect(extractBlockerTypeFromPattern(patterns[0].description)).toBe("aversion");
    expect(extractBlockerTypeFromPattern(patterns[1].description)).toBe("window");
  });

  it("returns null for an unrelated real Pattern description (A10 Pattern Miner regularity)", () => {
    // The live seed's real `pattern-priya-does-grocery-runs` description —
    // proves the discriminator correctly excludes non-friction patterns
    // even on genuine live graph data.
    expect(
      extractBlockerTypeFromPattern(
        "Grocery runs are consistently done by Priya, usually within 2 days of the prior run.",
      ),
    ).toBeNull();
  });

  it("returns null for a malformed prefix rather than throwing", () => {
    expect(extractBlockerTypeFromPattern("Friction pattern (not_a_real_type), Priya: x")).toBeNull();
    expect(extractBlockerTypeFromPattern("")).toBeNull();
  });
});

describe("findMatchingPattern / patternsForPerson", () => {
  it("finds an existing pattern by person and blocker type", () => {
    const patterns = getInitialFrictionPatterns();
    const found = findMatchingPattern(patterns, PRIYA_ID, "aversion");
    expect(found?.supportCount).toBe(3);
  });

  it("returns null when this person has no pattern of that type", () => {
    const patterns = getInitialFrictionPatterns();
    expect(findMatchingPattern(patterns, PRIYA_ID, "window")).toBeNull();
    expect(findMatchingPattern(patterns, DADI_ID, "aversion")).toBeNull();
  });

  it("returns an honestly empty list for a person with no friction pattern on file yet", () => {
    expect(patternsForPerson(getInitialFrictionPatterns(), AARAV_ID)).toHaveLength(0);
    expect(patternsForPerson(getInitialFrictionPatterns(), DADI_ID)).toHaveLength(0);
  });

  it("scopes patternsForPerson to the requested person only", () => {
    const patterns = getInitialFrictionPatterns();
    expect(patternsForPerson(patterns, PRIYA_ID)).toHaveLength(1);
    expect(patternsForPerson(patterns, MAYA_ID)).toHaveLength(1);
  });
});

describe("applyDiagnosisCorrection", () => {
  const baseCorrection: DiagnosisCorrection = {
    obligationId: getEyeCheckupDiagnosis().obligationId,
    personId: PRIYA_ID,
    originalDiagnosis: getEyeCheckupDiagnosis(),
    correctedBlockerType: "aversion",
    correctionNote: "The number was found in ten seconds once someone looked, that was never the real hold-up.",
    correctedBy: PRIYA_ID,
    correctedAt: "2026-08-26T10:00:00Z",
  };

  it("increments Priya's existing aversion pattern from 3 to 4 support and rebuilds confidence", () => {
    const initial = getInitialFrictionPatterns();
    const result = applyDiagnosisCorrection(initial, baseCorrection, "Priya");

    expect(result.wasIncrement).toBe(true);
    expect(result.writtenPattern.supportCount).toBe(4);
    expect(result.writtenPattern.confidence).toBeCloseTo(patternConfidence(4));
    expect(result.writtenPattern.personId).toBe(PRIYA_ID);
    expect(result.writtenPattern.blockerType).toBe("aversion");

    // Exactly one current aversion pattern for Priya afterward — the old
    // v3 entry recedes from the current view (see this function's own doc
    // comment on why), never duplicated alongside the new one.
    const priyaAversion = result.patterns.filter((p) => p.personId === PRIYA_ID && p.blockerType === "aversion");
    expect(priyaAversion).toHaveLength(1);
    expect(priyaAversion[0].supportCount).toBe(4);
  });

  it("the written pattern's description carries the real correction note and obligation id", () => {
    const result = applyDiagnosisCorrection(getInitialFrictionPatterns(), baseCorrection, "Priya");
    expect(result.writtenPattern.description).toContain(baseCorrection.correctionNote);
    expect(result.writtenPattern.description).toContain(baseCorrection.obligationId);
    expect(result.writtenPattern.description).toMatch(/^Friction pattern \(aversion\), Priya:/);
  });

  it("creates a brand-new support-count-1 pattern when this person has no matching blocker type yet", () => {
    const correction: DiagnosisCorrection = {
      ...baseCorrection,
      personId: DADI_ID,
      correctedBlockerType: "first_step_ambiguity",
    };
    const result = applyDiagnosisCorrection(getInitialFrictionPatterns(), correction, "Dadi");

    expect(result.wasIncrement).toBe(false);
    expect(result.writtenPattern.supportCount).toBe(1);
    expect(result.writtenPattern.confidence).toBeCloseTo(patternConfidence(1));
    // Dadi had zero patterns before; now has exactly one.
    expect(patternsForPerson(result.patterns, DADI_ID)).toHaveLength(1);
    // Every other person's patterns are untouched.
    expect(patternsForPerson(result.patterns, MAYA_ID)).toHaveLength(1);
  });

  it("never mutates the input patterns array (pure function)", () => {
    const initial = getInitialFrictionPatterns();
    const before = JSON.stringify(initial);
    applyDiagnosisCorrection(initial, baseCorrection, "Priya");
    expect(JSON.stringify(initial)).toBe(before);
  });
});

describe("stale-obligation fixture", () => {
  it("124 days matches the real gap between 2026-04-20 and SEED_NOW (2026-08-22)", () => {
    const detection = getStaleObligationDetection();
    const created = new Date("2026-04-20T09:00:00Z");
    const detected = new Date(detection.detectedAt);
    const diffDays = Math.round((detected.getTime() - created.getTime()) / (1000 * 60 * 60 * 24));
    expect(diffDays).toBe(detection.daysStale);
  });
});

describe("dental check-up demo narrative (spec §9.6's demo beat)", () => {
  it("has three chronological attempts, each diagnosing a different blocker type in sequence", () => {
    const attempts = getDentalCheckupAttempts();
    expect(attempts).toHaveLength(3);
    expect(attempts.map((a) => a.diagnosis.blockerType)).toEqual(["information", "first_step_ambiguity", "aversion"]);
    expect(attempts.every((a) => a.outcome === "failed")).toBe(true);
    // Chronological order.
    const times = attempts.map((a) => new Date(a.attemptedAt).getTime());
    expect(times).toEqual([...times].sort((a, b) => a - b));
  });

  it("the current diagnosis is a real re-diagnosis superseding the immediately prior type", () => {
    const current = getDentalCheckupCurrentDiagnosis();
    expect(current.isRediagnosis).toBe(true);
    expect(current.supersededDiagnosisType).toBe("first_step_ambiguity");
    expect(current.blockerType).toBe("aversion");
  });

  it("the slippage analysis triggers at the real attempt count and offers three genuinely different options", () => {
    const analysis = getDentalCheckupSlippageAnalysis();
    expect(analysis.attemptCount).toBe(getDentalCheckupAttempts().length);
    expect(analysis.escalationTriggered).toBe(true);
    expect(analysis.escalationOptions.map((o) => o.kind).sort()).toEqual(["delegate", "drop", "pay"]);
    const delegateOption = analysis.escalationOptions.find((o) => o.kind === "delegate");
    expect(delegateOption?.candidatePersonId).not.toBeNull();
    const payOption = analysis.escalationOptions.find((o) => o.kind === "pay");
    expect(payOption?.estimatedCost).toBeGreaterThan(0);
  });

  it("the modality switch resolves to a genuinely different modality", () => {
    const modalitySwitch = getDentalCheckupModalitySwitch();
    expect(modalitySwitch.fromModality).not.toBe(modalitySwitch.toModality);
    expect(modalitySwitch.fromModality).toBe("call");
  });

  it("the resolved window is on a day the household's own schedule has no conflict recorded for Priya", () => {
    const result = getDentalCheckupWindow();
    expect(result.bestWindow).not.toBeNull();
    expect(result.evaluations[0].overallRecommended).toBe(true);
    expect(result.evaluations[0].personAvailability).toBe("available");
  });
});

describe("eye check-up demo narrative (the correction-affordance target)", () => {
  it("diagnoses information and the fetch genuinely resolves it", () => {
    const diagnosis = getEyeCheckupDiagnosis();
    const fetch = getEyeCheckupInformationFetch();
    expect(diagnosis.blockerType).toBe("information");
    expect(fetch.fetched).toBe(true);
    expect(fetch.factText).not.toBeNull();
  });
});

describe("field-trip decision demo narrative", () => {
  it("narrows to exactly two distinct, mutually exclusive options", () => {
    const diagnosis = getFieldTripDiagnosis();
    const narrowing = getFieldTripDecisionNarrowing();
    expect(diagnosis.blockerType).toBe("decision");
    expect(narrowing.optionA).not.toBe(narrowing.optionB);
    expect(narrowing.optionA.length).toBeGreaterThan(0);
    expect(narrowing.optionB.length).toBeGreaterThan(0);
  });
});

describe("Dadi physio window-blocker demo narrative, real, computed verdicts", () => {
  it("diagnoses window", () => {
    expect(getDadiPhysioDiagnosis().blockerType).toBe("window");
  });

  it("computes all four AvailabilityVerdict states via the real ported algorithm, not hand-picked labels", () => {
    const candidates = getDadiPhysioCandidates();
    const fixtureConstraints = getDadiPhysioFixtureConstraints();
    const realDadiNapConstraint = {
      id: "constraint-dadi-nap",
      kind: "schedule" as const,
      severity: "soft" as const,
      structured: { days_of_week: "daily", start_time: "14:00", end_time: "16:00" },
    };

    // Candidate 0 (Mon afternoon): real nap window + fixture hard + legacy.
    const verdict0 = personAvailabilityForWindow(
      [realDadiNapConstraint, ...fixtureConstraints],
      new Date(candidates[0].window[0]),
      new Date(candidates[0].window[1]),
    );
    expect(verdict0).toBe("soft_avoid");

    // Candidate 1 (Tue morning): overlaps the fixture hard cardiology slot.
    const verdict1 = personAvailabilityForWindow(
      [realDadiNapConstraint, ...fixtureConstraints],
      new Date(candidates[1].window[0]),
      new Date(candidates[1].window[1]),
    );
    expect(verdict1).toBe("hard_blocked");

    // Candidate 2 (Wed evening): evaluated against only the legacy entry —
    // every schedule-kind constraint on file is unparseable.
    const legacyOnly = fixtureConstraints.filter((c) => c.id.includes("legacy"));
    const verdict2 = personAvailabilityForWindow(
      legacyOnly,
      new Date(candidates[2].window[0]),
      new Date(candidates[2].window[1]),
    );
    expect(verdict2).toBe("cannot_determine");

    // Candidate 3 (Thu late morning): clear of everything.
    const verdict3 = personAvailabilityForWindow(
      [realDadiNapConstraint, ...fixtureConstraints],
      new Date(candidates[3].window[0]),
      new Date(candidates[3].window[1]),
    );
    expect(verdict3).toBe("available");

    expect(new Set([verdict0, verdict1, verdict2, verdict3])).toEqual(
      new Set(["soft_avoid", "hard_blocked", "cannot_determine", "available"]),
    );
  });

  it("buildDadiPhysioWindowResult recommends exactly the Thursday candidate, with the real constraint present", () => {
    const realDadiNapConstraint = {
      id: DADI_NAP_CONSTRAINT_ID,
      kind: "schedule" as const,
      severity: "soft" as const,
      structured: { days_of_week: "daily", start_time: "14:00", end_time: "16:00" },
    };
    const result = buildDadiPhysioWindowResult(realDadiNapConstraint);
    expect(result.evaluations).toHaveLength(4);
    expect(result.evaluations.map((e) => e.personAvailability)).toEqual([
      "soft_avoid",
      "hard_blocked",
      "cannot_determine",
      "available",
    ]);
    const recommended = result.evaluations.filter((e) => e.overallRecommended);
    expect(recommended).toHaveLength(1);
    expect(recommended[0].window).toEqual(getDadiPhysioCandidates()[3].window);
    expect(result.bestWindow).toEqual(getDadiPhysioCandidates()[3].window);
  });

  it("buildDadiPhysioWindowResult degrades gracefully (never crashes) when the live constraint is unavailable", () => {
    const result = buildDadiPhysioWindowResult(null);
    expect(result.evaluations).toHaveLength(4);
    expect(result.bestWindow).not.toBeNull();
  });
});
