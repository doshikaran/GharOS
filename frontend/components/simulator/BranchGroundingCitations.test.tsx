import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BranchGroundingCitations } from "./BranchGroundingCitations";
import { getGroundingResults } from "@/lib/simulator";

describe("BranchGroundingCitations", () => {
  it("renders each citation as a real link with title, uri, and a retrieval timestamp, never a bare string", () => {
    const grounding = getGroundingResults().find((g) => g.citations.length > 0)!;
    render(<BranchGroundingCitations grounding={grounding} />);

    for (const citation of grounding.citations) {
      const link = screen.getByRole("link", { name: citation.title });
      expect(link).toHaveAttribute("href", citation.uri);
      expect(link).toHaveAttribute("target", "_blank");
    }
    expect(screen.getAllByText(/retrieved/i).length).toBeGreaterThan(0);
  });

  it("renders the zero-citation case distinctly, not as an empty/loading-looking gap", () => {
    const grounding = getGroundingResults().find((g) => g.citations.length === 0)!;
    expect(grounding).toBeDefined();
    render(<BranchGroundingCitations grounding={grounding} />);

    expect(screen.queryAllByRole("link")).toHaveLength(0);
    // Scoped to the fixed `role="status"` callout, not a bare text query —
    // `grounding.summary` is agent-produced free text that can itself
    // legitimately contain "no external source found" (see ADR-017's
    // honest-empty-case convention), so an unscoped text query is ambiguous
    // by construction whenever a fixture's summary echoes the same wording.
    expect(screen.getByRole("status")).toHaveTextContent(/no external source found/i);
  });

  it("renders a distinct message when no grounding was attempted at all", () => {
    render(<BranchGroundingCitations grounding={undefined} />);
    expect(screen.getByText(/no grounding attempted/i)).toBeInTheDocument();
  });
});
