import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { SimulatorExplorer } from "./SimulatorExplorer";
import { getDecisionFrame } from "@/lib/simulator";

describe("SimulatorExplorer", () => {
  it("renders the decision framing header, branch comparison, risk register, calibration, and interrogation mode by default", () => {
    render(<SimulatorExplorer />);

    expect(screen.getByText(getDecisionFrame().question)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Branch comparison" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Risk register" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Calibration" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Interrogation mode" })).toBeInTheDocument();
  });

  it("does not render the backward-mode panel until its tab is selected", () => {
    render(<SimulatorExplorer />);
    expect(screen.queryByLabelText("Backward mode analysis")).not.toBeInTheDocument();
  });

  it("switches to a distinct backward-mode view on tab click, hiding the forward panel", () => {
    render(<SimulatorExplorer />);

    fireEvent.click(screen.getByRole("tab", { name: /backward mode/i }));

    expect(screen.getByLabelText("Backward mode analysis")).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Branch comparison" })).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: /backward mode/i })).toHaveAttribute("aria-selected", "true");
  });

  it("switches back to forward mode on tab click", () => {
    render(<SimulatorExplorer />);
    fireEvent.click(screen.getByRole("tab", { name: /backward mode/i }));
    fireEvent.click(screen.getByRole("tab", { name: /forward/i }));

    expect(screen.getByRole("heading", { name: "Branch comparison" })).toBeInTheDocument();
    expect(screen.queryByLabelText("Backward mode analysis")).not.toBeInTheDocument();
  });

  it("never states a recommendation or verdict anywhere on this page, forward or backward", () => {
    const { unmount } = render(<SimulatorExplorer />);
    const forwardText = document.body.textContent?.toLowerCase() ?? "";
    unmount();

    render(<SimulatorExplorer />);
    fireEvent.click(screen.getByRole("tab", { name: /backward mode/i }));
    const backwardText = document.body.textContent?.toLowerCase() ?? "";

    // Concrete verdict-issuing phrases, not the bare words "recommend"/
    // "verdict" — this page's own honest copy legitimately explains the
    // constraint ("never a verdict on an emotionally-loaded family
    // decision"), so banning the words themselves would also ban stating
    // the guarantee; what must never appear is the system actually
    // recommending one.
    for (const phrase of [
      "you should choose",
      "the best branch is",
      "optimal choice",
      "we recommend branch",
      "our recommendation is",
      "i recommend",
    ]) {
      expect(forwardText).not.toContain(phrase);
      expect(backwardText).not.toContain(phrase);
    }
  });

  it("renders every branch's grounding citations inline, never collapsed behind a details/summary disclosure", () => {
    render(<SimulatorExplorer />);
    expect(document.querySelectorAll("details")).toHaveLength(0);
  });
});
