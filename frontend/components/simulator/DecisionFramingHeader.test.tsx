import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DecisionFramingHeader } from "./DecisionFramingHeader";
import { getDecisionFrame } from "@/lib/simulator";

describe("DecisionFramingHeader", () => {
  it("renders the question and the trigger", () => {
    const frame = getDecisionFrame();
    render(<DecisionFramingHeader frame={frame} />);
    expect(screen.getByText(frame.question)).toBeInTheDocument();
    expect(screen.getByText(frame.trigger)).toBeInTheDocument();
  });

  it("flags a false binary and lists every unconsidered option", () => {
    const frame = getDecisionFrame();
    render(<DecisionFramingHeader frame={frame} />);
    expect(screen.getByText("False binary detected")).toBeInTheDocument();
    for (const option of frame.unconsideredOptions) {
      expect(screen.getByText(option)).toBeInTheDocument();
    }
  });

  it("does not claim a false binary or list unconsidered options when none exist", () => {
    render(
      <DecisionFramingHeader
        frame={{
          decisionId: "decision-simple",
          question: "Should we renew the annual society membership?",
          trigger: "Renewal notice arrived.",
          isFalseBinary: false,
          unconsideredOptions: [],
          proposedBranchLabels: ["Renew", "Do not renew"],
        }}
      />,
    );
    expect(screen.getByText("Not flagged as a false binary")).toBeInTheDocument();
    expect(screen.queryByText(/left out/i)).not.toBeInTheDocument();
  });
});
