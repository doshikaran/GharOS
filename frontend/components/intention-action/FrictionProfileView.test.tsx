import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { AARAV_ID, DADI_ID, MAYA_ID, PRIYA_ID, applyDiagnosisCorrection, getInitialFrictionPatterns } from "@/lib/intention-action";
import { FrictionProfileView } from "./FrictionProfileView";

const people = [
  { personId: PRIYA_ID, displayName: "Priya" },
  { personId: AARAV_ID, displayName: "Aarav" },
  { personId: DADI_ID, displayName: "Dadi" },
  { personId: MAYA_ID, displayName: "Maya" },
];

describe("FrictionProfileView", () => {
  it("renders Priya's aversion pattern with its real support count phrased as accumulated evidence", () => {
    render(<FrictionProfileView patterns={getInitialFrictionPatterns()} people={people} />);
    expect(screen.getByText("Aversion blocker")).toBeInTheDocument();
    expect(screen.getByText("seen 3 times")).toBeInTheDocument();
  });

  it("renders Maya's window pattern", () => {
    render(<FrictionProfileView patterns={getInitialFrictionPatterns()} people={people} />);
    expect(screen.getByText("Window blocker")).toBeInTheDocument();
    expect(screen.getByText("seen 2 times")).toBeInTheDocument();
  });

  it("renders an honest empty state for a person with no pattern on file, never a fabricated claim", () => {
    render(<FrictionProfileView patterns={getInitialFrictionPatterns()} people={people} />);
    const emptyStates = screen.getAllByText("No friction pattern on file yet.");
    // Aarav and Dadi both start with none.
    expect(emptyStates).toHaveLength(2);
  });

  it("visibly reflects a correction's effect: support count grows from 3 to 4 and singular phrasing is used at 1", () => {
    const correction = {
      obligationId: "obligation-eye-checkup-dadi",
      personId: PRIYA_ID,
      originalDiagnosis: {
        obligationId: "obligation-eye-checkup-dadi",
        personId: PRIYA_ID,
        blockerType: "information" as const,
        diagnosisText: "x",
        evidence: [],
        confidence: 0.6,
        consideredAlternativeTypes: [],
        isRediagnosis: false,
        supersededDiagnosisType: null,
        modelTier: "pro" as const,
        promptVersion: "v1",
        invocationId: "inv",
        diagnosedAt: "2026-08-18T12:00:00Z",
      },
      correctedBlockerType: "aversion" as const,
      correctionNote: "Same call aversion as before.",
      correctedBy: PRIYA_ID,
      correctedAt: "2026-08-26T10:00:00Z",
    };
    const result = applyDiagnosisCorrection(getInitialFrictionPatterns(), correction, "Priya");

    render(<FrictionProfileView patterns={result.patterns} people={people} justUpdatedPatternId={result.writtenPattern.id} />);

    expect(screen.getByText("seen 4 times")).toBeInTheDocument();
    expect(screen.queryByText("seen 3 times")).not.toBeInTheDocument();
    expect(screen.getByText("Just updated")).toBeInTheDocument();
  });

  it("shows exactly one pattern row when a person has only one, and uses singular 'seen once'", () => {
    const patterns = [
      {
        id: "pattern-x-1",
        personId: DADI_ID,
        blockerType: "dependency" as const,
        description: "Friction pattern (dependency), Dadi: x (obligation obligation-x)",
        supportCount: 1,
        confidence: 0.6,
        createdAt: "2026-08-01T00:00:00Z",
      },
    ];
    render(<FrictionProfileView patterns={patterns} people={people} />);
    expect(screen.getByText("seen once")).toBeInTheDocument();
  });
});
