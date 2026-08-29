import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { buildLiveCostMatrix } from "@/lib/fair-allocator-matrix";
import type { GraphNode } from "@/lib/graph-types";
import { CostMatrix } from "./CostMatrix";

function personNode(id: string, displayName: string): GraphNode {
  return {
    id,
    type: "PERSON",
    label: displayName,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: "doc-school-whatsapp",
    region: "header",
    created_at: "2026-08-22T09:00:00Z",
    fields: { display_name: displayName },
  };
}

function obligationNode(id: string, title: string): GraphNode {
  return {
    id,
    type: "OBLIGATION",
    label: title,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: "doc-school-whatsapp",
    region: "msg-9",
    created_at: "2026-08-22T09:00:00Z",
    fields: { title, status: "assigned" },
  };
}

function valuationNode(id: string, personId: string, costs: Record<string, number>): GraphNode {
  return {
    id,
    type: "VALUATION_PROFILE",
    label: "mixed valuation",
    derivation: "inferred",
    confidence: 0.7,
    source_document_id: "doc-school-whatsapp",
    region: "derived",
    created_at: "2026-08-22T09:00:00Z",
    fields: { person_id: personId, costs, elicitation_method: "mixed" },
  };
}

const priya = personNode("person-priya", "Priya");
const maya = personNode("person-maya", "Maya");
const pickup = obligationNode("obligation-pickup-aarav", "Pick up Aarav from school");
const groceries = obligationNode("obligation-weekly-groceries", "Buy weekly groceries");
const priyaValuation = valuationNode("valuation-priya", "person-priya", {
  "obligation-pickup-aarav": 3.0,
  "obligation-weekly-groceries": 1.0,
});
const matrix = buildLiveCostMatrix([priya, maya, pickup, groceries, priyaValuation]);

function Wrapper() {
  const [confirmed, setConfirmed] = useState(false);
  return <CostMatrix matrix={matrix} confirmed={confirmed} onConfirm={() => setConfirmed(true)} />;
}

describe("CostMatrix", () => {
  it("renders a live-priced cell with its value and elicitation method", () => {
    render(<CostMatrix matrix={matrix} confirmed={false} onConfirm={vi.fn()} />);
    expect(screen.getByText("1.0")).toBeInTheDocument();
    expect(screen.getAllByText(/live · mixed/).length).toBeGreaterThan(0);
  });

  it("renders a person never asked about a task as an unmistakable 'not asked' cell, never a zero", () => {
    render(<CostMatrix matrix={matrix} confirmed={false} onConfirm={vi.fn()} />);
    const cell = screen.getByLabelText("Maya was not asked about Pick up Aarav from school");
    expect(within(cell).getByText("not asked")).toBeInTheDocument();
    expect(within(cell).queryByText("0")).not.toBeInTheDocument();
    expect(within(cell).queryByText("0.0")).not.toBeInTheDocument();
  });

  it("shows an unconfirmed banner before confirmation and a confirmed badge after", () => {
    render(<Wrapper />);
    expect(screen.getByText(/Not yet confirmed/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /Review & confirm this matrix/ }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm this matrix" }));
    expect(screen.getByText("Confirmed")).toBeInTheDocument();
    expect(screen.queryByText(/Not yet confirmed/)).not.toBeInTheDocument();
  });

  it("does not confirm when the dialog is dismissed via Cancel", () => {
    const onConfirm = vi.fn();
    render(<CostMatrix matrix={matrix} confirmed={false} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("button", { name: /Review & confirm this matrix/ }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onConfirm).not.toHaveBeenCalled();
  });

  it("lets a household member edit a cell, and the dialog restates the edit before confirming", () => {
    const onConfirm = vi.fn();
    render(<CostMatrix matrix={matrix} confirmed={false} onConfirm={onConfirm} />);
    fireEvent.click(screen.getByRole("switch", { name: /Edit matrix/ }));
    const input = screen.getByLabelText("Priya's cost for Buy weekly groceries");
    fireEvent.change(input, { target: { value: "4.5" } });
    fireEvent.click(screen.getByRole("button", { name: /Review & confirm this matrix/ }));
    expect(screen.getByText(/Priya, Buy weekly groceries: 1.0 → 4.5/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Confirm this matrix" }));
    expect(onConfirm).toHaveBeenCalledTimes(1);
  });

  it("renders a real, honest empty state when there is no graph data yet", () => {
    render(<CostMatrix matrix={buildLiveCostMatrix([])} confirmed={false} onConfirm={vi.fn()} />);
    expect(screen.getByText(/No people or obligations/)).toBeInTheDocument();
  });
});
