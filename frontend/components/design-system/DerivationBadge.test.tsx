import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DerivationBadge } from "./DerivationBadge";

describe("DerivationBadge", () => {
  it("renders without crashing for extracted", () => {
    render(<DerivationBadge derivation="extracted" />);
    expect(screen.getByText("Extracted")).toBeInTheDocument();
  });

  it("renders inferred with a dashed-border class and confidence", () => {
    render(<DerivationBadge derivation="inferred" confidence={0.82} />);
    const label = screen.getByText("Inferred");
    expect(label.closest("span")?.className).toContain("inferred");
    expect(screen.getByText("82%")).toBeInTheDocument();
  });

  it("renders ambiguous with a dotted-border class", () => {
    render(<DerivationBadge derivation="ambiguous" />);
    expect(screen.getByText("Ambiguous").closest("span")?.className).toContain("ambiguous");
  });

  it("exposes the derivation tag as a data attribute for downstream styling/tests", () => {
    render(<DerivationBadge derivation="extracted" />);
    expect(screen.getByText("Extracted").closest("[data-derivation]")).toHaveAttribute(
      "data-derivation",
      "extracted",
    );
  });
});
