import { describe, expect, it } from "vitest";
import type { GraphNode, GraphSnapshot } from "./graph-types";
import {
  branchesForDecision,
  buildDecisionReplay,
  concedersForDecision,
  listDecisions,
  positionsForDecision,
  searchDecisions,
} from "./council-history";

/**
 * A hand-built `GraphSnapshot` shaped exactly like a real
 * `/graph/snapshot` response after A49 Recorder has written one resolved
 * car-purchase council — same node/edge envelope shape `lib/graph-api.ts`
 * fetches for real, just constructed by hand here so this file's tests
 * need no server. Two decisions are included so `searchDecisions` and the
 * "only this decision's own branches/positions" filtering both have
 * something real to discriminate against.
 */
function makeNode(partial: Partial<GraphNode> & Pick<GraphNode, "id" | "type" | "label">): GraphNode {
  return {
    derivation: null,
    confidence: null,
    source_document_id: null,
    region: null,
    created_at: null,
    fields: {},
    ...partial,
  };
}

const CAR_DECISION = makeNode({
  id: "decision-buy-car",
  type: "DECISION",
  label: "Replace the household car, or keep repairing it?",
  fields: {
    question: "Replace the household car, or keep repairing it?",
    trigger: "Three maintenance ledger events in three months.",
    status: "resolved",
    resolution_summary: "Household bought the compact SUV.",
    rationale: "Minimax regret selected the compact SUV; Care's mobility constraint eliminated the hatchback.",
  },
});

const SCHOOL_DECISION = makeNode({
  id: "decision-choose-school",
  type: "DECISION",
  label: "Which school for Aarav's transfer?",
  fields: {
    question: "Which school for Aarav's transfer?",
    trigger: "Redevelopment relocation forced a catchment change.",
    status: "briefed",
    resolution_summary: null,
    rationale: null,
  },
});

const HATCHBACK_BRANCH = makeNode({
  id: "branch-compact-hatchback",
  type: "BRANCH",
  label: "Compact hatchback",
  fields: { decision_id: "decision-buy-car", label: "Compact hatchback", projected_impacts: {}, grounding_refs: [], critiques: [] },
});

const SUV_BRANCH = makeNode({
  id: "branch-compact-suv",
  type: "BRANCH",
  label: "Compact SUV",
  fields: {
    decision_id: "decision-buy-car",
    label: "Compact SUV",
    projected_impacts: { finance: "Fits the computed EMI band." },
    grounding_refs: ["cite-service-network"],
    critiques: ["Thin authorised service network in this city."],
  },
});

const CARE_POSITION = makeNode({
  id: "position-care-car",
  type: "COUNCIL_POSITION",
  label: "Care position on decision-buy-car",
  fields: {
    decision_id: "decision-buy-car",
    held_by_agent: "A43",
    stance: "opposes",
    branch_id: "branch-compact-hatchback",
    reasoning: "Dadi's mobility constraint eliminates the hatchback.",
    evidence_refs: ["constraint-dadi-mobility"],
  },
});

const FINANCE_POSITION = makeNode({
  id: "position-finance-car",
  type: "COUNCIL_POSITION",
  label: "Finance position on decision-buy-car",
  fields: {
    decision_id: "decision-buy-car",
    held_by_agent: "A42",
    stance: "neutral",
    branch_id: null,
    reasoning: "Real ledger history sets the affordability band.",
    evidence_refs: ["ledger-car-repair-jun"],
  },
});

const PRIYA = makeNode({ id: "person-priya", type: "PERSON", label: "Priya" });
const MAYA = makeNode({ id: "person-maya", type: "PERSON", label: "Maya" });

const CONCEDED_BY_EDGE = {
  id: "edge-conceded-maya-car",
  type: "conceded_by",
  from_id: "decision-buy-car",
  to_id: "person-maya",
  derivation: null,
  confidence: null,
  is_conflict: false,
};

const SNAPSHOT: GraphSnapshot = {
  nodes: [CAR_DECISION, SCHOOL_DECISION, HATCHBACK_BRANCH, SUV_BRANCH, CARE_POSITION, FINANCE_POSITION, PRIYA, MAYA],
  edges: [CONCEDED_BY_EDGE],
};

describe("listDecisions", () => {
  it("returns every DECISION node, mapped to its question/trigger/status", () => {
    const decisions = listDecisions(SNAPSHOT);
    expect(decisions).toHaveLength(2);
    const car = decisions.find((d) => d.id === "decision-buy-car");
    expect(car?.question).toBe("Replace the household car, or keep repairing it?");
    expect(car?.status).toBe("resolved");
    expect(car?.resolutionSummary).toBe("Household bought the compact SUV.");
  });

  it("ignores non-DECISION nodes entirely", () => {
    const decisions = listDecisions(SNAPSHOT);
    expect(decisions.some((d) => d.id === "branch-compact-suv")).toBe(false);
  });
});

describe("searchDecisions", () => {
  it("matches case-insensitively against the question", () => {
    const decisions = listDecisions(SNAPSHOT);
    const results = searchDecisions(decisions, "SCHOOL");
    expect(results).toHaveLength(1);
    expect(results[0].id).toBe("decision-choose-school");
  });

  it("returns every decision for an empty/whitespace query", () => {
    const decisions = listDecisions(SNAPSHOT);
    expect(searchDecisions(decisions, "   ")).toHaveLength(2);
  });

  it("returns nothing for a query matching no decision", () => {
    const decisions = listDecisions(SNAPSHOT);
    expect(searchDecisions(decisions, "spaceship")).toHaveLength(0);
  });
});

describe("branchesForDecision / positionsForDecision", () => {
  it("returns only branches whose decision_id matches, never another decision's branches", () => {
    const branches = branchesForDecision(SNAPSHOT, "decision-buy-car");
    expect(branches.map((b) => b.id).sort()).toEqual(["branch-compact-hatchback", "branch-compact-suv"]);
  });

  it("returns only positions naming this decision via decision_id, never inferred from an edge", () => {
    const positions = positionsForDecision(SNAPSHOT, "decision-buy-car");
    expect(positions.map((p) => p.heldByAgent).sort()).toEqual(["A42", "A43"]);
  });

  it("returns an empty list for a decision with no branches/positions in the snapshot", () => {
    expect(branchesForDecision(SNAPSHOT, "decision-choose-school")).toHaveLength(0);
    expect(positionsForDecision(SNAPSHOT, "decision-choose-school")).toHaveLength(0);
  });
});

describe("concedersForDecision", () => {
  it("resolves the real conceded_by edge to a labelled person, not a bare id", () => {
    const conceders = concedersForDecision(SNAPSHOT, "decision-buy-car");
    expect(conceders).toEqual([{ personId: "person-maya", personLabel: "Maya" }]);
  });

  it("never returns a person from a conceded_by edge pointing at a different decision", () => {
    expect(concedersForDecision(SNAPSHOT, "decision-choose-school")).toHaveLength(0);
  });
});

describe("buildDecisionReplay, the full 'why did we buy this car' assembly", () => {
  it("assembles decision, branches, positions, and conceders together for a real decision id", () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car");
    expect(replay).not.toBeNull();
    expect(replay!.decision.id).toBe("decision-buy-car");
    expect(replay!.branches).toHaveLength(2);
    expect(replay!.positions).toHaveLength(2);
    expect(replay!.conceders).toEqual([{ personId: "person-maya", personLabel: "Maya" }]);
  });

  it("returns null for an id naming no real DECISION node in the snapshot", () => {
    expect(buildDecisionReplay(SNAPSHOT, "decision-does-not-exist")).toBeNull();
  });
});
