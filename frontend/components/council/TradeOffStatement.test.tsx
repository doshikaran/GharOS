import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { branchLabel, getCouncilBrief, personLabel } from "@/lib/council";
import { TradeOffStatement } from "./TradeOffStatement";

describe("TradeOffStatement", () => {
  it("names the real winning branch and the real people it costs/favours most", () => {
    const brief = getCouncilBrief();
    render(<TradeOffStatement brief={brief} />);

    expect(screen.getByText(branchLabel(brief.resolution.winningBranchId))).toBeInTheDocument();
    expect(screen.getByText(new RegExp(personLabel(brief.resolution.mostCostlyTo!)))).toBeInTheDocument();
  });

  it("frames itself as a brief, never a verdict the household must accept", () => {
    const brief = getCouncilBrief();
    render(<TradeOffStatement brief={brief} />);
    expect(screen.getByText("Brief, not a verdict")).toBeInTheDocument();
    expect(screen.getByText(/household still weighs it and decides/i)).toBeInTheDocument();
  });

  it("never states that the household must accept the resolution, and never uses the word 'debate'", () => {
    const brief = getCouncilBrief();
    render(<TradeOffStatement brief={brief} />);
    const text = document.body.textContent?.toLowerCase() ?? "";
    expect(text).not.toContain("debate");
    for (const phrase of ["you should choose", "the household must", "must accept", "final decision"]) {
      expect(text).not.toContain(phrase);
    }
  });
});
