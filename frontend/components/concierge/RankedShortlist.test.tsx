import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getAaravToothacheRanking } from "@/lib/concierge";
import { RankedShortlist } from "./RankedShortlist";

describe("RankedShortlist", () => {
  it("renders every ranked provider with its own real reasons — #1 and #2 are never the same text", () => {
    const ranking = getAaravToothacheRanking();
    render(<RankedShortlist ranking={ranking} />);
    const [first, second] = ranking.ranked;
    for (const reason of first.reasons) {
      expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
    }
    for (const reason of second.reasons) {
      expect(screen.getAllByText(reason).length).toBeGreaterThan(0);
    }
    expect(first.reasons).not.toEqual(second.reasons);
  });

  it("visibly flags the demoted provider with a no-show badge", () => {
    const ranking = getAaravToothacheRanking();
    render(<RankedShortlist ranking={ranking} />);
    const demoted = ranking.ranked.find((p) => p.demotedForReliability);
    expect(demoted).toBeDefined();
    expect(screen.getByTestId(`demoted-${demoted?.providerId}`)).toHaveTextContent("Demoted");
  });

  it("renders the full score-components breakdown for every provider, not just the headline score", () => {
    const ranking = getAaravToothacheRanking();
    render(<RankedShortlist ranking={ranking} />);
    for (const provider of ranking.ranked) {
      for (const value of Object.values(provider.scoreComponents)) {
        expect(screen.getAllByText(value.toFixed(2)).length).toBeGreaterThan(0);
      }
    }
  });

  it("renders the ranking narrative and urgency badge", () => {
    const ranking = getAaravToothacheRanking();
    render(<RankedShortlist ranking={ranking} />);
    expect(screen.getByText(ranking.narrative)).toBeInTheDocument();
    expect(screen.getByText("Elevated urgency")).toBeInTheDocument();
  });

  it("renders an empty state when there are no ranked providers", () => {
    const ranking = getAaravToothacheRanking();
    render(<RankedShortlist ranking={{ ...ranking, ranked: [] }} />);
    expect(screen.getByText(/No providers found/)).toBeInTheDocument();
  });
});
