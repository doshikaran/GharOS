import { describe, expect, it } from "vitest";
import {
  agentDomainLabel,
  branchLabel,
  buildTradeOffStatement,
  eliminatingAgentForBranch,
  getCouncilBrief,
  getCouncilComposition,
  getSurvivingBranchIds,
  maxRegretForBranch,
  personLabel,
  regretForBranch,
} from "./council";

describe("fixture cross-consistency (this phase's own bar: every id referenced elsewhere exists in the same fixture set)", () => {
  it("every SpecialistPosition.agentId is a convened specialist", () => {
    const composition = getCouncilComposition();
    const brief = getCouncilBrief();
    for (const position of brief.specialistPositions) {
      expect(composition.convenedSpecialistIds).toContain(position.agentId);
    }
  });

  it("every DelegateScoring.personId is a convened delegate, and matches its own valuationProfile.personId", () => {
    const composition = getCouncilComposition();
    const brief = getCouncilBrief();
    expect(brief.delegateScorings.length).toBeGreaterThan(0);
    for (const scoring of brief.delegateScorings) {
      expect(composition.convenedDelegatePersonIds).toContain(scoring.personId);
      expect(scoring.valuationProfile.personId).toBe(scoring.personId);
    }
  });

  it("no two specialists share the exact same evidenceRefs (distinct information, ADR-019/spec §12.2 design rule 1)", () => {
    const brief = getCouncilBrief();
    const refSets = brief.specialistPositions.map((p) => [...p.evidenceRefs].sort().join("|"));
    expect(new Set(refSets).size).toBe(refSets.length);
  });

  it("no two specialists share the exact same reasoning text", () => {
    const brief = getCouncilBrief();
    const reasonings = brief.specialistPositions.map((p) => p.reasoning);
    expect(new Set(reasonings).size).toBe(reasonings.length);
  });

  it("brief.decisionId and brief.question match the composition", () => {
    const composition = getCouncilComposition();
    const brief = getCouncilBrief();
    expect(brief.decisionId).toBe(composition.decisionId);
    expect(brief.question).toBe(composition.question);
  });
});

describe("hard-constraint elimination (Gate 12: eliminates, never scores down)", () => {
  it("every eliminated branch id (from any specialist) is absent from every delegate's cost matrix", () => {
    const brief = getCouncilBrief();
    const eliminated = new Set(brief.specialistPositions.flatMap((p) => p.eliminatedBranchIds));
    expect(eliminated.size).toBeGreaterThan(0);
    for (const scoring of brief.delegateScorings) {
      for (const branchId of eliminated) {
        expect(Object.keys(scoring.valuationProfile.costs)).not.toContain(branchId);
      }
    }
  });

  it("the resolution's eliminatedBranchIds matches the union of every specialist's own eliminations", () => {
    const brief = getCouncilBrief();
    const fromSpecialists = new Set(brief.specialistPositions.flatMap((p) => p.eliminatedBranchIds));
    expect(new Set(brief.resolution.eliminatedBranchIds)).toEqual(fromSpecialists);
  });

  it("Care (A43) is the specialist who eliminated the hatchback, named explicitly, not left unattributed", () => {
    const brief = getCouncilBrief();
    const eliminator = eliminatingAgentForBranch(brief.specialistPositions, brief.resolution.eliminatedBranchIds[0]);
    expect(eliminator).toBe("A43");
  });

  it("the winning branch was never eliminated", () => {
    const brief = getCouncilBrief();
    expect(brief.resolution.eliminatedBranchIds).not.toContain(brief.resolution.winningBranchId);
  });
});

describe("minimax-regret resolution is arithmetically honest (ADR-019 Decision 3, Savage 1951)", () => {
  it("every delegate's regret for the winning branch matches CouncilResolution.regretByPerson exactly", () => {
    const brief = getCouncilBrief();
    const surviving = getSurvivingBranchIds();
    const recomputed = regretForBranch(brief.delegateScorings, brief.resolution.winningBranchId, surviving);
    expect(recomputed).toEqual(brief.resolution.regretByPerson);
  });

  it("the winning branch actually minimises the maximum regret across all surviving branches", () => {
    const brief = getCouncilBrief();
    const surviving = getSurvivingBranchIds();
    const maxRegrets = surviving.map((branchId) => ({
      branchId,
      maxRegret: maxRegretForBranch(brief.delegateScorings, branchId, surviving),
    }));
    const winnerEntry = maxRegrets.find((entry) => entry.branchId === brief.resolution.winningBranchId);
    expect(winnerEntry).toBeDefined();
    for (const entry of maxRegrets) {
      expect(winnerEntry!.maxRegret).toBeLessThanOrEqual(entry.maxRegret);
    }
  });

  it("regretByPerson keys exactly match the convened delegate person ids", () => {
    const composition = getCouncilComposition();
    const brief = getCouncilBrief();
    expect(new Set(Object.keys(brief.resolution.regretByPerson))).toEqual(
      new Set(composition.convenedDelegatePersonIds),
    );
  });

  it("mostCostlyTo is the delegate with the highest regret for the winner; mostFavorableTo the lowest, ties broken by lexical personId order, the same documented-arbitrary-tiebreak discipline ADR-019 Decision 3 names for branch ties", () => {
    const brief = getCouncilBrief();
    const entries = Object.entries(brief.resolution.regretByPerson);

    const maxRegret = Math.max(...entries.map(([, regret]) => regret));
    const costliest = entries
      .filter(([, regret]) => regret === maxRegret)
      .map(([personId]) => personId)
      .sort()[0];

    const minRegret = Math.min(...entries.map(([, regret]) => regret));
    const favorable = entries
      .filter(([, regret]) => regret === minRegret)
      .map(([personId]) => personId)
      .sort()[0];

    expect(brief.resolution.mostCostlyTo).toBe(costliest);
    expect(brief.resolution.mostFavorableTo).toBe(favorable);
  });

  it("concedingPersonIds is exactly the set of delegates with strictly positive regret for the winner", () => {
    const brief = getCouncilBrief();
    const expected = Object.entries(brief.resolution.regretByPerson)
      .filter(([, regret]) => regret > 0)
      .map(([personId]) => personId);
    expect(new Set(brief.resolution.concedingPersonIds)).toEqual(new Set(expected));
  });
});

describe("adversary attacks the arbiter's own winning branch, not a separate 'leading option' (ADR-019 Decision 7)", () => {
  it("targetBranchId equals the resolution's winningBranchId", () => {
    const brief = getCouncilBrief();
    expect(brief.adversaryAttack.targetBranchId).toBe(brief.resolution.winningBranchId);
  });

  it("cites at least one real household OUTCOME id, never a generic risk template with no citation", () => {
    const brief = getCouncilBrief();
    expect(brief.adversaryAttack.citedOutcomeIds.length).toBeGreaterThan(0);
    for (const outcomeId of brief.adversaryAttack.citedOutcomeIds) {
      expect(outcomeId.startsWith("outcome-")).toBe(true);
    }
  });
});

describe("risk register", () => {
  it("is a flat, non-empty list of strings", () => {
    const brief = getCouncilBrief();
    expect(brief.riskRegister.length).toBeGreaterThan(0);
    for (const entry of brief.riskRegister) {
      expect(typeof entry).toBe("string");
      expect(entry.length).toBeGreaterThan(0);
    }
  });
});

describe("buildTradeOffStatement, real prose, never a bare number dump or a synthesized consensus", () => {
  it("names the winning branch, the real costly/favorable people, and their exact regret numbers", () => {
    const brief = getCouncilBrief();
    const statement = buildTradeOffStatement(brief);

    expect(statement).toContain(branchLabel(brief.resolution.winningBranchId));
    expect(statement).toContain(personLabel(brief.resolution.mostCostlyTo!));
    expect(statement).toContain(personLabel(brief.resolution.mostFavorableTo!));
    expect(statement).toContain(brief.resolution.regretByPerson[brief.resolution.mostCostlyTo!].toFixed(1));
    expect(statement).toContain(brief.resolution.regretByPerson[brief.resolution.mostFavorableTo!].toFixed(1));
  });

  it("quotes each named delegate's own real reasoning verbatim, never inventing a dimension they didn't state", () => {
    const brief = getCouncilBrief();
    const statement = buildTradeOffStatement(brief);
    const costlyScoring = brief.delegateScorings.find((d) => d.personId === brief.resolution.mostCostlyTo);
    const favorableScoring = brief.delegateScorings.find((d) => d.personId === brief.resolution.mostFavorableTo);
    expect(statement).toContain(costlyScoring!.reasoning);
    expect(statement).toContain(favorableScoring!.reasoning);
  });

  it("names every conceding person, never silently omitting a real concession", () => {
    const brief = getCouncilBrief();
    const statement = buildTradeOffStatement(brief);
    for (const personId of brief.resolution.concedingPersonIds) {
      expect(statement).toContain(personLabel(personId));
    }
  });

  it("never says the household must accept this, and never uses the word 'debate'", () => {
    const brief = getCouncilBrief();
    const statement = buildTradeOffStatement(brief).toLowerCase();
    expect(statement).not.toContain("debate");
    expect(statement).not.toContain("must accept");
    expect(statement).not.toContain("final decision");
  });
});

describe("display lookups", () => {
  it("resolves a known agent and person id to a human label", () => {
    expect(agentDomainLabel("A42")).toContain("Finance");
    expect(personLabel("person-priya")).toBe("Priya");
  });

  it("falls back to the raw id for an unknown agent/person/branch", () => {
    expect(agentDomainLabel("A99")).toBe("A99");
    expect(personLabel("person-unknown")).toBe("person-unknown");
    expect(branchLabel("branch-unknown")).toBe("branch-unknown");
  });
});

describe('the word "debate" never appears in this fixture file\'s own data', () => {
  it("checks every string field across the whole brief and composition", () => {
    const composition = getCouncilComposition();
    const brief = getCouncilBrief();
    const haystack = JSON.stringify({ composition, brief }).toLowerCase();
    expect(haystack).not.toContain("debate");
  });
});
