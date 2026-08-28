import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BranchCritiqueView } from "./BranchCritiqueView";
import { getBranchCritiques } from "@/lib/simulator";

describe("BranchCritiqueView", () => {
  it("renders over-optimistic claims and omitted second-order effects under distinct headings", () => {
    const critique = getBranchCritiques()[0];
    render(<BranchCritiqueView critique={critique} />);

    expect(screen.getByText("Over-optimistic claims")).toBeInTheDocument();
    expect(screen.getByText("Omitted second-order effects")).toBeInTheDocument();
    for (const claim of critique.overOptimisticClaims) {
      expect(screen.getByText(claim)).toBeInTheDocument();
    }
    for (const effect of critique.omittedSecondOrderEffects) {
      expect(screen.getByText(effect)).toBeInTheDocument();
    }
  });

  it("renders the revised confidence note", () => {
    const critique = getBranchCritiques()[0];
    render(<BranchCritiqueView critique={critique} />);
    expect(screen.getByText(critique.revisedConfidenceNote)).toBeInTheDocument();
  });

  it("renders nothing when no critique exists for this branch", () => {
    const { container } = render(<BranchCritiqueView critique={undefined} />);
    expect(container).toBeEmptyDOMElement();
  });
});
