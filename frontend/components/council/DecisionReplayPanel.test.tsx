import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { buildDecisionReplay } from "@/lib/council-history";
import type { GraphNode, GraphSnapshot } from "@/lib/graph-types";
import { DecisionReplayPanel } from "./DecisionReplayPanel";

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

const MAYA = makeNode({ id: "person-maya", type: "PERSON", label: "Maya" });

const SNAPSHOT: GraphSnapshot = {
  nodes: [CAR_DECISION, HATCHBACK_BRANCH, SUV_BRANCH, CARE_POSITION, FINANCE_POSITION, MAYA],
  edges: [
    {
      id: "edge-conceded-maya-car",
      type: "conceded_by",
      from_id: "decision-buy-car",
      to_id: "person-maya",
      derivation: null,
      confidence: null,
      is_conflict: false,
    },
  ],
};

describe("DecisionReplayPanel", () => {
  it("renders the decision's question, trigger, resolution summary, and rationale", () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car")!;
    render(<DecisionReplayPanel replay={replay} />);

    expect(screen.getByText("Replace the household car, or keep repairing it?")).toBeInTheDocument();
    expect(screen.getByText(/Three maintenance ledger events/)).toBeInTheDocument();
    expect(screen.getByText(/Household bought the compact SUV/)).toBeInTheDocument();
    expect(screen.getByText(/Minimax regret selected the compact SUV/)).toBeInTheDocument();
  });

  it("renders every branch this decision considered, with its own projected impacts and critiques", () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car")!;
    render(<DecisionReplayPanel replay={replay} />);

    expect(screen.getByText("Compact hatchback")).toBeInTheDocument();
    expect(screen.getByText("Compact SUV")).toBeInTheDocument();
    expect(screen.getByText(/Fits the computed EMI band/)).toBeInTheDocument();
    expect(screen.getByText(/Thin authorised service network/)).toBeInTheDocument();
  });

  it("renders every council position naming this decision, each keeping its own agent, stance, and evidence", () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car")!;
    render(<DecisionReplayPanel replay={replay} />);

    expect(screen.getByText("A43")).toBeInTheDocument();
    expect(screen.getByText("A42")).toBeInTheDocument();
    expect(screen.getByText(/Dadi's mobility constraint eliminates the hatchback/)).toBeInTheDocument();
    expect(screen.getByText("constraint-dadi-mobility")).toBeInTheDocument();
    const positions = screen.getByLabelText("Council positions");
    expect(within(positions).getByText("opposes")).toBeInTheDocument();
    expect(within(positions).getByText("neutral")).toBeInTheDocument();
  });

  it("names the branch a position is about by its real label, not a bare id", () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car")!;
    render(<DecisionReplayPanel replay={replay} />);
    expect(screen.getByText(/On: Compact hatchback/)).toBeInTheDocument();
  });

  it("renders who conceded, resolved to a real labelled person", () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car")!;
    render(<DecisionReplayPanel replay={replay} />);
    expect(screen.getByText("Maya")).toBeInTheDocument();
  });

  it('never renders the word "debate"', () => {
    const replay = buildDecisionReplay(SNAPSHOT, "decision-buy-car")!;
    render(<DecisionReplayPanel replay={replay} />);
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
