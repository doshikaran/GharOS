import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { getCouncilBrief } from "@/lib/council";
import { SpecialistPositions } from "./SpecialistPositions";

describe("SpecialistPositions", () => {
  it("renders one card per specialist, each naming its own subgraph domain", () => {
    const brief = getCouncilBrief();
    render(<SpecialistPositions positions={brief.specialistPositions} />);

    expect(screen.getByText(/Finance: Ledger subgraph/)).toBeInTheDocument();
    expect(screen.getByText(/Care: Constraint subgraph/)).toBeInTheDocument();
    expect(screen.getByText(/Logistics: Obligation subgraph/)).toBeInTheDocument();
  });

  it("renders Finance and Care with visibly different evidence content, not generic interchangeable prose", () => {
    const brief = getCouncilBrief();
    render(<SpecialistPositions positions={brief.specialistPositions} />);

    // Finance's reasoning cites real currency figures; Care's cites a real
    // constraint id — genuinely different kinds of evidence, not the same
    // sentence with the agent name swapped.
    expect(screen.getByText(/₹34,500/)).toBeInTheDocument();
    expect(screen.getByText(/constraint-dadi-mobility/)).toBeInTheDocument();
  });

  it("flags Care's elimination distinctly, naming the eliminated branch, without hiding which specialist eliminated it", () => {
    const brief = getCouncilBrief();
    render(<SpecialistPositions positions={brief.specialistPositions} />);

    const note = screen.getByRole("note");
    expect(within(note).getByText(/Compact hatchback/)).toBeInTheDocument();
    expect(note.textContent).toMatch(/hard constraint/i);
    expect(note.textContent).toMatch(/not scored down/i);
  });

  it("renders every evidenceRef as its own list item", () => {
    const brief = getCouncilBrief();
    render(<SpecialistPositions positions={brief.specialistPositions} />);

    for (const position of brief.specialistPositions) {
      for (const ref of position.evidenceRefs) {
        expect(screen.getByText(ref)).toBeInTheDocument();
      }
    }
  });

  it('never renders the word "debate"', () => {
    const brief = getCouncilBrief();
    render(<SpecialistPositions positions={brief.specialistPositions} />);
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
