import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RiskRegister } from "./RiskRegister";
import { buildRiskRegister, getBranchCritiques, getBranchProjections } from "@/lib/simulator";

describe("RiskRegister", () => {
  it("renders every entry with its branch label, category, and text", () => {
    const entries = buildRiskRegister(getBranchCritiques(), getBranchProjections());
    render(<RiskRegister entries={entries} />);

    expect(screen.getAllByRole("listitem")).toHaveLength(entries.length);
    for (const entry of entries) {
      expect(screen.getByText(entry.text)).toBeInTheDocument();
    }
    expect(screen.getAllByText("over-optimistic claim").length).toBeGreaterThan(0);
    expect(screen.getAllByText("omitted second-order effect").length).toBeGreaterThan(0);
  });

  it("renders an honest empty state when there are no risks", () => {
    render(<RiskRegister entries={[]} />);
    expect(screen.getByText(/no risks raised/i)).toBeInTheDocument();
    expect(screen.queryAllByRole("listitem")).toHaveLength(0);
  });
});
