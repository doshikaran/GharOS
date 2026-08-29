import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { LanguageSpanChip } from "./LanguageSpanChip";

describe("LanguageSpanChip", () => {
  it("renders the span text and its display-mapped language label", () => {
    render(<LanguageSpanChip span={{ text: "Aarav ko Friday ko", language: "hi", confidence: 0.92 }} />);
    expect(screen.getByText("Aarav ko Friday ko")).toBeInTheDocument();
    expect(screen.getByText("Hindi")).toBeInTheDocument();
  });

  it("falls back to the raw code for an unrecognised language", () => {
    render(<LanguageSpanChip span={{ text: "bonjour", language: "fr", confidence: 0.7 }} />);
    expect(screen.getByText("FR")).toBeInTheDocument();
  });

  it("flags a low-confidence span visibly", () => {
    render(<LanguageSpanChip span={{ text: "mumble", language: "en", confidence: 0.3 }} />);
    const chip = screen.getByText("mumble").closest("span[data-low-confidence]");
    expect(chip).toHaveAttribute("data-low-confidence", "true");
  });

  it("does not flag a confident span", () => {
    render(<LanguageSpanChip span={{ text: "clear speech", language: "en", confidence: 0.95 }} />);
    const chip = screen.getByText("clear speech").closest("span[data-low-confidence]");
    expect(chip).toHaveAttribute("data-low-confidence", "false");
  });
});
