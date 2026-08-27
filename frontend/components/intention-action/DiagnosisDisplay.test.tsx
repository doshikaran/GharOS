import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getDentalCheckupAttempts, getDentalCheckupCurrentDiagnosis, getFieldTripDiagnosis } from "@/lib/intention-action";
import { DiagnosisDisplay } from "./DiagnosisDisplay";

describe("DiagnosisDisplay", () => {
  it("renders diagnosisText as a first-class, standalone statement", () => {
    const diagnosis = getFieldTripDiagnosis();
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="Choose how to pay for Aarav's field trip" personName="Priya" />);
    expect(screen.getByTestId("diagnosis-text")).toHaveTextContent(diagnosis.diagnosisText);
  });

  it("renders the diagnosed blocker type's real label, not just a raw enum string", () => {
    const diagnosis = getFieldTripDiagnosis();
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="x" personName="Priya" />);
    expect(screen.getByText("Decision blocker")).toBeInTheDocument();
    expect(screen.queryByText("decision")).not.toBeInTheDocument();
  });

  it("renders every piece of evidence", () => {
    const diagnosis = getFieldTripDiagnosis();
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="x" personName="Priya" />);
    for (const item of diagnosis.evidence) {
      expect(screen.getByText(item)).toBeInTheDocument();
    }
  });

  it("shows the re-diagnosis banner with the superseded type when isRediagnosis is true", () => {
    const diagnosis = getDentalCheckupCurrentDiagnosis();
    expect(diagnosis.isRediagnosis).toBe(true);
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="x" personName="Priya" />);
    expect(screen.getByText(/This is a re-diagnosis/)).toBeInTheDocument();
    expect(screen.getAllByText("First-step ambiguity").length).toBeGreaterThan(0);
  });

  it("shows no re-diagnosis banner for a first diagnosis", () => {
    const diagnosis = getDentalCheckupAttempts()[0].diagnosis;
    expect(diagnosis.isRediagnosis).toBe(false);
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="x" personName="Priya" />);
    expect(screen.queryByText(/This is a re-diagnosis/)).not.toBeInTheDocument();
  });

  it("renders considered-and-rejected alternative types", () => {
    const diagnosis = getDentalCheckupCurrentDiagnosis();
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="x" personName="Priya" />);
    expect(screen.getByText("Considered and rejected")).toBeInTheDocument();
    expect(diagnosis.consideredAlternativeTypes).toContain("dependency");
    expect(screen.getByText("Dependency blocker")).toBeInTheDocument();
  });

  it("renders a confidence readout", () => {
    const diagnosis = getFieldTripDiagnosis();
    render(<DiagnosisDisplay diagnosis={diagnosis} obligationTitle="x" personName="Priya" />);
    expect(screen.getByRole("progressbar", { name: "Confidence" })).toBeInTheDocument();
  });
});
