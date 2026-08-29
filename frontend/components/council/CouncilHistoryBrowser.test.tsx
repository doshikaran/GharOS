import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { GraphNode, GraphSnapshot } from "@/lib/graph-types";
import { CouncilHistoryBrowser } from "./CouncilHistoryBrowser";

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
    rationale: "Minimax regret selected the compact SUV.",
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

const SUV_BRANCH = makeNode({
  id: "branch-compact-suv",
  type: "BRANCH",
  label: "Compact SUV",
  fields: {
    decision_id: "decision-buy-car",
    label: "Compact SUV",
    projected_impacts: {},
    grounding_refs: [],
    critiques: [],
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
    branch_id: null,
    reasoning: "Dadi's mobility constraint eliminates the hatchback.",
    evidence_refs: ["constraint-dadi-mobility"],
  },
});

const MAYA = makeNode({ id: "person-maya", type: "PERSON", label: "Maya" });

const SNAPSHOT: GraphSnapshot = {
  nodes: [CAR_DECISION, SCHOOL_DECISION, SUV_BRANCH, CARE_POSITION, MAYA],
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

function stubFetch(response: GraphSnapshot | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      response
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(response) } as Response)
        : Promise.reject(new TypeError("Failed to fetch")),
    ),
  );
}

describe("CouncilHistoryBrowser", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the snapshot resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading past council decisions");
  });

  it("shows a real error rather than a blank browser when the snapshot fetch fails", async () => {
    stubFetch(null);
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load past decisions/));
  });

  it("shows an honest empty state when the graph holds no council decisions yet", async () => {
    stubFetch({ nodes: [], edges: [] });
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);
    await screen.findByText(/No past council decisions recorded yet/);
  });

  it("lists every past decision by its question", async () => {
    stubFetch(SNAPSHOT);
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);

    await screen.findByText("Replace the household car, or keep repairing it?");
    expect(screen.getByText("Which school for Aarav's transfer?")).toBeInTheDocument();
  });

  it("search filters the decision list case-insensitively by question", async () => {
    stubFetch(SNAPSHOT);
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);

    await screen.findByText("Replace the household car, or keep repairing it?");
    fireEvent.change(screen.getByPlaceholderText(/why did we buy this car/i), { target: { value: "school" } });

    expect(screen.queryByText("Replace the household car, or keep repairing it?")).not.toBeInTheDocument();
    expect(screen.getByText("Which school for Aarav's transfer?")).toBeInTheDocument();
  });

  it("selecting a decision replays its branches, positions, and conceders", async () => {
    stubFetch(SNAPSHOT);
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);

    await screen.findByText("Replace the household car, or keep repairing it?");
    expect(screen.getByText(/Select a past decision to replay/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Replace the household car/ }));

    expect(screen.getByText("Compact SUV")).toBeInTheDocument();
    expect(screen.getByText("A43")).toBeInTheDocument();
    expect(screen.getByText(/Dadi's mobility constraint eliminates the hatchback/)).toBeInTheDocument();
    expect(screen.getByText("Maya")).toBeInTheDocument();
  });

  it('never renders the word "debate"', async () => {
    stubFetch(SNAPSHOT);
    render(<CouncilHistoryBrowser baseUrl="http://api.example" />);
    await screen.findByText("Replace the household car, or keep repairing it?");
    fireEvent.click(screen.getByRole("button", { name: /Replace the household car/ }));
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
