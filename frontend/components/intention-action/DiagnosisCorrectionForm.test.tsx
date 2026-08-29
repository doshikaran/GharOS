import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { getEyeCheckupDiagnosis, PRIYA_ID, DADI_ID, type DiagnosisCorrection } from "@/lib/intention-action";
import { DiagnosisCorrectionForm } from "./DiagnosisCorrectionForm";

const people = [
  { personId: PRIYA_ID, displayName: "Priya" },
  { personId: DADI_ID, displayName: "Dadi" },
];

const diagnosis = getEyeCheckupDiagnosis();
const fixedNow = () => new Date("2026-08-26T10:00:00Z");

describe("DiagnosisCorrectionForm", () => {
  it("submits nothing until a correction note is entered", () => {
    render(<DiagnosisCorrectionForm diagnosis={diagnosis} people={people} onSubmit={vi.fn()} submittedCorrection={null} now={fixedNow} />);
    expect(screen.getByRole("button", { name: "Submit correction" })).toBeDisabled();
  });

  it("submits a real DiagnosisCorrection with the chosen type, corrector, and note", () => {
    const onSubmit = vi.fn();
    render(<DiagnosisCorrectionForm diagnosis={diagnosis} people={people} onSubmit={onSubmit} submittedCorrection={null} now={fixedNow} />);

    fireEvent.change(screen.getByLabelText("Actual blocker type"), { target: { value: "aversion" } });
    fireEvent.change(screen.getByLabelText("Corrected by"), { target: { value: PRIYA_ID } });
    fireEvent.change(screen.getByLabelText("Correction note"), {
      target: { value: "The number was found instantly, that was never the real hold-up." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));

    expect(onSubmit).toHaveBeenCalledTimes(1);
    const correction = onSubmit.mock.calls[0][0] as DiagnosisCorrection;
    expect(correction.correctedBlockerType).toBe("aversion");
    expect(correction.correctedBy).toBe(PRIYA_ID);
    expect(correction.correctionNote).toBe("The number was found instantly, that was never the real hold-up.");
    expect(correction.obligationId).toBe(diagnosis.obligationId);
    expect(correction.originalDiagnosis).toBe(diagnosis);
    expect(correction.correctedAt).toBe(fixedNow().toISOString());
  });

  it("renders a confirmation state once submittedCorrection is set, never the form again", () => {
    const submitted: DiagnosisCorrection = {
      obligationId: diagnosis.obligationId,
      personId: diagnosis.personId,
      originalDiagnosis: diagnosis,
      correctedBlockerType: "aversion",
      correctionNote: "Same aversion pattern as before.",
      correctedBy: PRIYA_ID,
      correctedAt: "2026-08-26T10:00:00Z",
    };
    render(<DiagnosisCorrectionForm diagnosis={diagnosis} people={people} onSubmit={vi.fn()} submittedCorrection={submitted} />);

    expect(screen.getByText("Correction recorded")).toBeInTheDocument();
    expect(screen.getByText(/Same aversion pattern as before\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Submit correction" })).not.toBeInTheDocument();
  });

  it("states plainly that the correction is not yet persisted to the real graph", () => {
    const submitted: DiagnosisCorrection = {
      obligationId: diagnosis.obligationId,
      personId: diagnosis.personId,
      originalDiagnosis: diagnosis,
      correctedBlockerType: "aversion",
      correctionNote: "note",
      correctedBy: PRIYA_ID,
      correctedAt: "2026-08-26T10:00:00Z",
    };
    render(<DiagnosisCorrectionForm diagnosis={diagnosis} people={people} onSubmit={vi.fn()} submittedCorrection={submitted} />);
    expect(screen.getByText(/no live write endpoint yet/)).toBeInTheDocument();
  });
});
