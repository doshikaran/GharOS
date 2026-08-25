import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { NODE_TYPES } from "@/lib/graph-types";
import { GraphLegend } from "./GraphLegend";

describe("GraphLegend", () => {
  it("renders one legend entry for every one of the 16 node types", () => {
    render(<GraphLegend />);
    expect(screen.getAllByRole("listitem")).toHaveLength(NODE_TYPES.length + 4); // + derivation x3 + conflict
  });

  it("labels the person and constraint types distinctly", () => {
    render(<GraphLegend />);
    expect(screen.getByText("Person")).toBeInTheDocument();
    expect(screen.getByText("Constraint")).toBeInTheDocument();
  });

  it("shows all three derivation labels plus the conflict entry", () => {
    render(<GraphLegend />);
    expect(screen.getByText("Extracted")).toBeInTheDocument();
    expect(screen.getByText("Inferred")).toBeInTheDocument();
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
    expect(screen.getByText("Conflict")).toBeInTheDocument();
  });
});
