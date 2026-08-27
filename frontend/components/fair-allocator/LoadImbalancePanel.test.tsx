import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getLoadImbalanceFindings, AARAV_ID, DADI_ID, MAYA_ID, PRIYA_ID } from "@/lib/fair-allocator";
import { LoadImbalancePanel } from "./LoadImbalancePanel";

const PERSON_NAMES: Record<string, string> = {
  [PRIYA_ID]: "Priya",
  [MAYA_ID]: "Maya",
  [DADI_ID]: "Dadi",
  [AARAV_ID]: "Aarav",
};

function renderPanel() {
  return render(<LoadImbalancePanel findings={getLoadImbalanceFindings()} personName={(id) => PERSON_NAMES[id] ?? id} />);
}

describe("LoadImbalancePanel", () => {
  it("renders a card for every household member with expected vs observed share", () => {
    renderPanel();
    for (const name of ["Priya", "Maya", "Dadi", "Aarav"]) {
      expect(screen.getByRole("heading", { name })).toBeInTheDocument();
    }
    expect(screen.getByText("48%")).toBeInTheDocument(); // Priya's expected share
    expect(screen.getByText("55%")).toBeInTheDocument(); // Priya's observed share
  });

  it("shows evidence text, not just a verdict label", () => {
    renderPanel();
    expect(screen.getByText(/covered for Maya's night-shift-constrained availability/)).toBeInTheDocument();
  });

  it("flags Priya's creeping imbalance and Maya's balanced verdict distinctly", () => {
    renderPanel();
    expect(screen.getByText("Creeping imbalance")).toBeInTheDocument();
    expect(screen.getAllByText("Balanced").length).toBe(3);
  });

  it("renders a real, honest empty state with no findings", () => {
    render(<LoadImbalancePanel findings={[]} personName={(id) => id} />);
    expect(screen.getByText(/No load-imbalance findings/)).toBeInTheDocument();
  });
});
