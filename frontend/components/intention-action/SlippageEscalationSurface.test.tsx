import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { DADI_ID, getDentalCheckupAttempts, getDentalCheckupSlippageAnalysis } from "@/lib/intention-action";
import { SlippageEscalationSurface } from "./SlippageEscalationSurface";

const delegateName = (personId: string) => (personId === DADI_ID ? "Dadi" : personId);

describe("SlippageEscalationSurface", () => {
  it("renders every historical attempt with its diagnosis type and outcome", () => {
    const attempts = getDentalCheckupAttempts();
    render(
      <SlippageEscalationSurface
        obligationTitle="Book Aarav's dental check-up"
        attempts={attempts}
        analysis={getDentalCheckupSlippageAnalysis()}
        delegateName={delegateName}
      />,
    );
    for (const attempt of attempts) {
      expect(screen.getByText(`Attempt ${attempt.attemptNumber}`)).toBeInTheDocument();
    }
    expect(screen.getAllByText("Failed")).toHaveLength(attempts.length);
  });

  it("renders the re-diagnosis framing when the analysis includes one", () => {
    render(
      <SlippageEscalationSurface
        obligationTitle="x"
        attempts={getDentalCheckupAttempts()}
        analysis={getDentalCheckupSlippageAnalysis()}
        delegateName={delegateName}
      />,
    );
    expect(screen.getByText(/Re-diagnosis:/)).toBeInTheDocument();
    expect(screen.getByText(/the first diagnosis may have been wrong/)).toBeInTheDocument();
  });

  it("renders all three real escalation options with real, decidable context — never a resolve button", () => {
    render(
      <SlippageEscalationSurface
        obligationTitle="x"
        attempts={getDentalCheckupAttempts()}
        analysis={getDentalCheckupSlippageAnalysis()}
        delegateName={delegateName}
      />,
    );
    expect(screen.getByTestId("escalation-option-drop")).toBeInTheDocument();
    expect(screen.getByTestId("escalation-option-delegate")).toHaveTextContent("Dadi");
    expect(screen.getByTestId("escalation-option-pay")).toHaveTextContent("₹150");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders nothing under 'Escalation' when escalationTriggered is false", () => {
    const analysis = { ...getDentalCheckupSlippageAnalysis(), escalationTriggered: false };
    render(
      <SlippageEscalationSurface obligationTitle="x" attempts={getDentalCheckupAttempts()} analysis={analysis} delegateName={delegateName} />,
    );
    expect(screen.queryByText("Escalation")).not.toBeInTheDocument();
  });
});
