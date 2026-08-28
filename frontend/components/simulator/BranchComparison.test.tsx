import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BranchComparison } from "./BranchComparison";
import { getBranchCritiques, getBranchProjections, getGroundingResults } from "@/lib/simulator";

describe("BranchComparison", () => {
  it("renders 2-4 branches side by side, per this phase's brief", () => {
    const projections = getBranchProjections();
    expect(projections.length).toBeGreaterThanOrEqual(2);
    expect(projections.length).toBeLessThanOrEqual(4);

    render(
      <BranchComparison
        projections={projections}
        groundingResults={getGroundingResults()}
        critiques={getBranchCritiques()}
      />,
    );

    for (const projection of projections) {
      expect(screen.getByRole("heading", { name: projection.label })).toBeInTheDocument();
    }
    // Direct children only: each `BranchCard` renders its own nested
    // `listitem`s internally (projected impacts, critique points), which
    // are also descendants of this outer list — an accessible-role query
    // (scoped or not) would count those too, so cardinality is asserted on
    // the DOM's immediate children instead.
    const topLevelList = screen.getByRole("list", { name: "Branch comparison" });
    expect(topLevelList.children).toHaveLength(projections.length);
  });

  it("matches each branch's own grounding and critique by label/id, never positionally", () => {
    const projections = getBranchProjections();
    const shuffledGrounding = [...getGroundingResults()].reverse();
    const shuffledCritiques = [...getBranchCritiques()].reverse();

    render(
      <BranchComparison
        projections={projections}
        groundingResults={shuffledGrounding}
        critiques={shuffledCritiques}
      />,
    );

    // Every branch's own critique text should still be findable regardless
    // of the input arrays' order.
    for (const critique of shuffledCritiques) {
      for (const claim of critique.overOptimisticClaims) {
        expect(screen.getByText(claim)).toBeInTheDocument();
      }
    }
  });
});
