import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { GraphSnapshot } from "@/lib/graph-types";
import { FairAllocatorExplorer } from "./FairAllocatorExplorer";

const snapshot: GraphSnapshot = {
  nodes: [
    {
      id: "person-priya",
      type: "PERSON",
      label: "Priya",
      derivation: "extracted",
      confidence: 0.9,
      source_document_id: "doc-school-whatsapp",
      region: "header",
      created_at: "2026-08-22T09:00:00Z",
      fields: { display_name: "Priya" },
    },
    {
      id: "person-maya",
      type: "PERSON",
      label: "Maya",
      derivation: "extracted",
      confidence: 0.85,
      source_document_id: "doc-attendance-register",
      region: "header",
      created_at: "2026-08-22T09:00:00Z",
      fields: { display_name: "Maya" },
    },
    {
      id: "obligation-weekly-groceries",
      type: "OBLIGATION",
      label: "Buy weekly groceries",
      derivation: "extracted",
      confidence: 0.88,
      source_document_id: "doc-freshmart-receipt",
      region: "whole-document",
      created_at: "2026-08-22T09:00:00Z",
      fields: { title: "Buy weekly groceries", status: "completed" },
    },
    {
      id: "obligation-renew-prescription",
      type: "OBLIGATION",
      label: "Renew Dadi's blood-pressure prescription",
      derivation: "inferred",
      confidence: 0.8,
      source_document_id: "doc-pharmacy-sms",
      region: "msg-1",
      created_at: "2026-08-22T09:00:00Z",
      fields: { title: "Renew Dadi's blood-pressure prescription", status: "completed" },
    },
    {
      id: "obligation-visit-pharmacy",
      type: "OBLIGATION",
      label: "Collect prescription from pharmacy",
      derivation: "inferred",
      confidence: 0.75,
      source_document_id: "doc-pharmacy-sms",
      region: "msg-2",
      created_at: "2026-08-22T09:00:00Z",
      fields: { title: "Collect prescription from pharmacy", status: "assigned" },
    },
    {
      id: "valuation-priya",
      type: "VALUATION_PROFILE",
      label: "mixed valuation",
      derivation: "inferred",
      confidence: 0.7,
      source_document_id: "doc-school-whatsapp",
      region: "derived",
      created_at: "2026-08-22T09:00:00Z",
      fields: {
        person_id: "person-priya",
        costs: { "obligation-weekly-groceries": 1.0 },
        elicitation_method: "mixed",
      },
    },
  ],
  edges: [],
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

describe("FairAllocatorExplorer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the snapshot resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<FairAllocatorExplorer baseUrl="http://api.example" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the household's cost matrix");
  });

  it("shows a real error rather than a blank page when the snapshot fetch fails", async () => {
    stubFetch(null);
    render(<FairAllocatorExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load the cost matrix/));
  });

  it("renders the live matrix and gates the allocation behind confirmation", async () => {
    stubFetch(snapshot);
    render(<FairAllocatorExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByText("1.0")).toBeInTheDocument());
    expect(screen.getByText(/Confirm the cost matrix above/)).toBeInTheDocument();
    expect(screen.queryByText(/Envy-free up to one item/)).not.toBeInTheDocument();
  });

  it("reveals the allocation, explanations, and renegotiation demo once the matrix is confirmed", async () => {
    stubFetch(snapshot);
    render(<FairAllocatorExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByText("1.0")).toBeInTheDocument());

    fireEvent.click(screen.getByRole("button", { name: /Review & confirm this matrix/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm this matrix" }));

    expect(screen.getByText(/Envy-free up to one item \(EF1\) — holds/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Per-person fairness explanations" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Renegotiation" })).toBeInTheDocument();
    expect(screen.getByText(/just started night shifts/)).toBeInTheDocument();
  });

  it("renders the load-imbalance panel for every household member regardless of confirmation state", async () => {
    stubFetch(snapshot);
    render(<FairAllocatorExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByText("1.0")).toBeInTheDocument());
    expect(screen.getByRole("heading", { name: "Priya", level: 3 })).toBeInTheDocument();
  });
});
