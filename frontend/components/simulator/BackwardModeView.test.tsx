import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { BackwardModeView } from "./BackwardModeView";
import { getBackwardModeAnalysis } from "@/lib/simulator";

describe("BackwardModeView", () => {
  it("renders the plan, assumed failure point, confidence note, and every mitigation", () => {
    const analysis = getBackwardModeAnalysis();
    render(<BackwardModeView analysis={analysis} />);

    expect(screen.getByText(analysis.planDescription)).toBeInTheDocument();
    expect(screen.getByText(analysis.assumedFailurePoint)).toBeInTheDocument();
    expect(screen.getByText(analysis.confidenceNote)).toBeInTheDocument();
    for (const mitigation of analysis.suggestedMitigations) {
      expect(screen.getByText(mitigation)).toBeInTheDocument();
    }
  });

  it("renders every supporting outcome id", () => {
    const analysis = getBackwardModeAnalysis();
    render(<BackwardModeView analysis={analysis} />);
    for (const id of analysis.supportingOutcomeIds) {
      expect(screen.getByText(id)).toBeInTheDocument();
    }
  });

  it("explicitly captions itself as informational, not an automatic action", () => {
    render(<BackwardModeView analysis={getBackwardModeAnalysis()} />);
    expect(screen.getByRole("note")).toHaveTextContent(/informational only/i);
    expect(screen.getByRole("note").textContent?.toLowerCase()).toContain("does not automatically act");
  });
});
