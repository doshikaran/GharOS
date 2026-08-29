import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import type { GraphNode, JustificationResponse } from "@/lib/graph-types";
import { JustificationPanel } from "./JustificationPanel";

function node(id: string, label: string): GraphNode {
  return {
    id,
    type: "OBLIGATION",
    label,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: null,
    region: null,
    created_at: "2026-08-20T00:00:00Z",
    fields: {},
  };
}

const nodesById = new Map<string, GraphNode>([
  ["obligation-1", node("obligation-1", "Pay maintenance")],
  ["doc-1", node("doc-1", "Field trip email")],
]);

const response: JustificationResponse = {
  root_node_id: "obligation-1",
  steps: [
    { node_id: "obligation-1", depth: 0, via_edge: null },
    {
      node_id: "doc-1",
      depth: 1,
      via_edge: { id: "edge-1", type: "implies", from_id: "doc-1", to_id: "obligation-1" },
    },
  ],
  source_documents: [{ id: "doc-1", channel: "email", region: "0-40" }],
};

describe("JustificationPanel", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("renders a legible, ordered, plain-language chain", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(response) } as Response));

    render(
      <JustificationPanel
        baseUrl="http://api.example"
        rootNodeId="obligation-1"
        nodesById={nodesById}
        onHighlightChange={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText("Pay maintenance")).toBeInTheDocument());
    expect(screen.getByText(/implied by/)).toBeInTheDocument();
    expect(screen.getByText(/Field trip email/)).toBeInTheDocument();
    // The chain itself is a 2-step <ol>; the source-documents list below it
    // is a separate <ul> and is asserted in its own test further down.
    const chain = screen.getByText("Pay maintenance").closest("ol");
    expect(chain).not.toBeNull();
    expect(within(chain as HTMLElement).getAllByRole("listitem")).toHaveLength(2);
  });

  it("calls onHighlightChange with the exact node/edge ids on the path once loaded", async () => {
    const onHighlightChange = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(response) } as Response));

    render(
      <JustificationPanel
        baseUrl="http://api.example"
        rootNodeId="obligation-1"
        nodesById={nodesById}
        onHighlightChange={onHighlightChange}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(onHighlightChange).toHaveBeenCalledWith({
      nodeIds: new Set(["obligation-1", "doc-1"]),
      edgeIds: new Set(["edge-1"]),
    }));
  });

  it("clears the highlight on unmount", async () => {
    const onHighlightChange = vi.fn();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(response) } as Response));

    const { unmount } = render(
      <JustificationPanel
        baseUrl="http://api.example"
        rootNodeId="obligation-1"
        nodesById={nodesById}
        onHighlightChange={onHighlightChange}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(onHighlightChange).toHaveBeenCalledWith(expect.objectContaining({ nodeIds: expect.anything() })));
    unmount();
    expect(onHighlightChange).toHaveBeenLastCalledWith(null);
  });

  it("renders the source documents list", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(response) } as Response));

    render(
      <JustificationPanel
        baseUrl="http://api.example"
        rootNodeId="obligation-1"
        nodesById={nodesById}
        onHighlightChange={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByText(/email, 0-40/)).toBeInTheDocument());
  });

  it("shows a real error rather than a blank panel on a failed fetch", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(
      <JustificationPanel
        baseUrl="http://api.example"
        rootNodeId="obligation-1"
        nodesById={nodesById}
        onHighlightChange={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load the justification chain/));
  });
});
