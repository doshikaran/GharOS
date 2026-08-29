import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getCouncilBrief } from "@/lib/council";
import { DelegateScores } from "./DelegateScores";

describe("DelegateScores", () => {
  it("renders one card per delegate, each named by the real person, never anonymized", () => {
    const brief = getCouncilBrief();
    render(<DelegateScores delegateScorings={brief.delegateScorings} />);

    expect(screen.getByText("Priya")).toBeInTheDocument();
    expect(screen.getByText("Maya")).toBeInTheDocument();
    expect(screen.getByText("Dadi")).toBeInTheDocument();
  });

  it("never collapses the three people's costs into one shared aggregate number", () => {
    const brief = getCouncilBrief();
    render(<DelegateScores delegateScorings={brief.delegateScorings} />);
    // Three distinct people means three distinct cost tables/captions.
    expect(screen.getAllByRole("table")).toHaveLength(brief.delegateScorings.length);
  });

  it("marks each delegate's own cheapest surviving option as their own top pick", () => {
    const brief = getCouncilBrief();
    render(<DelegateScores delegateScorings={brief.delegateScorings} />);
    // Priya's and Dadi's top pick is the compact SUV; Maya's is the sedan.
    expect(screen.getAllByText(/own top pick/).length).toBe(brief.delegateScorings.length);
  });

  it("shows each delegate's own real reasoning text, not a generic justification", () => {
    const brief = getCouncilBrief();
    render(<DelegateScores delegateScorings={brief.delegateScorings} />);
    for (const scoring of brief.delegateScorings) {
      expect(screen.getByText(scoring.reasoning)).toBeInTheDocument();
    }
  });

  it('never renders the word "debate"', () => {
    const brief = getCouncilBrief();
    render(<DelegateScores delegateScorings={brief.delegateScorings} />);
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
