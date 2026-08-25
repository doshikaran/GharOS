import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { GraphNode } from "@/lib/graph-types";
import { NodeInspector } from "./NodeInspector";

const extractedNode: GraphNode = {
  id: "obligation-1",
  type: "OBLIGATION",
  label: "Pay maintenance",
  derivation: "extracted",
  confidence: 0.87,
  source_document_id: "doc-1",
  region: "0-10",
  created_at: "2026-08-20T00:00:00Z",
  fields: { due_date: "2026-08-30", amount_minor: 250000, is_paid: false },
};

const ambiguousNoSourceNode: GraphNode = {
  id: "pattern-1",
  type: "PATTERN",
  label: "Late payments trend",
  derivation: "ambiguous",
  confidence: 0.4,
  source_document_id: null,
  region: null,
  created_at: "2026-08-21T00:00:00Z",
  fields: {},
};

// SourceRegionViewer does real network fetches — stub it out here so this
// test stays focused on NodeInspector's own rendering contract.
vi.mock("./SourceRegionViewer", () => ({
  SourceRegionViewer: () => <div data-testid="source-region-viewer-stub" />,
}));

describe("NodeInspector", () => {
  it("renders the node's type and label", () => {
    render(<NodeInspector node={extractedNode} baseUrl="http://api.example" onClose={vi.fn()} onExplain={vi.fn()} />);
    expect(screen.getByText("Pay maintenance")).toBeInTheDocument();
    expect(screen.getByText("OBLIGATION")).toBeInTheDocument();
  });

  it("renders every key in fields", () => {
    render(<NodeInspector node={extractedNode} baseUrl="http://api.example" onClose={vi.fn()} onExplain={vi.fn()} />);
    expect(screen.getByText("Due Date")).toBeInTheDocument();
    expect(screen.getByText("2026-08-30")).toBeInTheDocument();
    expect(screen.getByText("Amount Minor")).toBeInTheDocument();
    expect(screen.getByText("250000")).toBeInTheDocument();
    expect(screen.getByText("Is Paid")).toBeInTheDocument();
    expect(screen.getByText("false")).toBeInTheDocument();
  });

  it("renders derivation and confidence via DerivationBadge, not a raw number", () => {
    render(<NodeInspector node={extractedNode} baseUrl="http://api.example" onClose={vi.fn()} onExplain={vi.fn()} />);
    expect(screen.getByText("Extracted")).toBeInTheDocument();
    expect(screen.getByText("87%")).toBeInTheDocument();
  });

  it("fetches and renders the source region when source_document_id is set", () => {
    render(<NodeInspector node={extractedNode} baseUrl="http://api.example" onClose={vi.fn()} onExplain={vi.fn()} />);
    expect(screen.getByTestId("source-region-viewer-stub")).toBeInTheDocument();
  });

  it("shows an honest message instead of a broken panel when source_document_id is null", () => {
    render(
      <NodeInspector node={ambiguousNoSourceNode} baseUrl="http://api.example" onClose={vi.fn()} onExplain={vi.fn()} />,
    );
    expect(screen.queryByTestId("source-region-viewer-stub")).not.toBeInTheDocument();
    expect(screen.getByText(/No single source document/)).toBeInTheDocument();
  });

  it("calls onExplain with the node id when 'Explain this' is clicked", () => {
    const onExplain = vi.fn();
    render(<NodeInspector node={extractedNode} baseUrl="http://api.example" onClose={vi.fn()} onExplain={onExplain} />);
    fireEvent.click(screen.getByRole("button", { name: "Explain this" }));
    expect(onExplain).toHaveBeenCalledWith("obligation-1");
  });

  it("calls onClose when the close button is clicked", () => {
    const onClose = vi.fn();
    render(<NodeInspector node={extractedNode} baseUrl="http://api.example" onClose={onClose} onExplain={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "Close node inspector" }));
    expect(onClose).toHaveBeenCalled();
  });
});
