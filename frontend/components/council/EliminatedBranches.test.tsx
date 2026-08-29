import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getCouncilBrief } from "@/lib/council";
import { EliminatedBranches } from "./EliminatedBranches";

describe("EliminatedBranches", () => {
  it("renders the eliminated branch struck through", () => {
    const brief = getCouncilBrief();
    render(
      <EliminatedBranches
        eliminatedBranchIds={brief.resolution.eliminatedBranchIds}
        positions={brief.specialistPositions}
      />,
    );

    const struckText = document.querySelector("s");
    expect(struckText).toBeInTheDocument();
    expect(struckText?.textContent).toMatch(/hatchback/i);
  });

  it("never renders an eliminated option in a way indistinguishable from a scored, surviving option, it always names the eliminating specialist", () => {
    const brief = getCouncilBrief();
    render(
      <EliminatedBranches
        eliminatedBranchIds={brief.resolution.eliminatedBranchIds}
        positions={brief.specialistPositions}
      />,
    );

    expect(screen.getByText(/Eliminated by Care/)).toBeInTheDocument();
    expect(screen.getByText(/hard constraint, not a low score/i)).toBeInTheDocument();
  });

  it("renders an honest empty state when nothing was eliminated", () => {
    render(<EliminatedBranches eliminatedBranchIds={[]} positions={[]} />);
    expect(screen.getByText(/No hard constraint eliminated/)).toBeInTheDocument();
  });

  it('never renders the word "debate"', () => {
    const brief = getCouncilBrief();
    render(
      <EliminatedBranches
        eliminatedBranchIds={brief.resolution.eliminatedBranchIds}
        positions={brief.specialistPositions}
      />,
    );
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
