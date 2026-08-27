import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BLOCKER_TYPES, BLOCKER_TYPE_META } from "@/lib/intention-action";
import { BlockerTaxonomyLegend } from "./BlockerTaxonomyLegend";

describe("BlockerTaxonomyLegend", () => {
  it("renders all six blocker types with their real label and description", () => {
    render(<BlockerTaxonomyLegend />);
    for (const type of BLOCKER_TYPES) {
      expect(screen.getByText(BLOCKER_TYPE_META[type].label)).toBeInTheDocument();
      expect(screen.getByText(BLOCKER_TYPE_META[type].shortDescription)).toBeInTheDocument();
    }
  });

  it("gives every one of the six types a visually distinct card (never two sharing a badge variant)", () => {
    render(<BlockerTaxonomyLegend />);
    const variants = BLOCKER_TYPES.map((type) => {
      const card = screen.getByTestId(`blocker-type-card-${type}`);
      return card.querySelector("[data-variant]")?.getAttribute("data-variant");
    });
    expect(new Set(variants).size).toBe(BLOCKER_TYPES.length);
  });

  it("marks the highlighted type distinctly from the rest", () => {
    render(<BlockerTaxonomyLegend highlighted="aversion" />);
    expect(screen.getByTestId("blocker-type-card-aversion")).toHaveAttribute("data-highlighted", "true");
    expect(screen.getByTestId("blocker-type-card-information")).toHaveAttribute("data-highlighted", "false");
  });

  it("renders no highlight by default", () => {
    render(<BlockerTaxonomyLegend />);
    for (const type of BLOCKER_TYPES) {
      expect(screen.getByTestId(`blocker-type-card-${type}`)).toHaveAttribute("data-highlighted", "false");
    }
  });
});
