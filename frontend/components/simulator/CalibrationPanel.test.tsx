import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CalibrationPanel } from "./CalibrationPanel";
import { getCalibrationEstimate } from "@/lib/simulator";

describe("CalibrationPanel", () => {
  it("renders the thin-history case distinctly, with no fabricated mean/stdev", () => {
    const estimate = getCalibrationEstimate("relocation")!;
    render(<CalibrationPanel estimate={estimate} />);

    expect(screen.getByText("Thin history")).toBeInTheDocument();
    expect(screen.getByText(estimate.honestNote)).toBeInTheDocument();
    expect(screen.queryByText("Mean variance")).not.toBeInTheDocument();
    expect(screen.queryByText("Std. deviation")).not.toBeInTheDocument();
  });

  it("renders real mean/stdev/confidence band once the sample clears the threshold", () => {
    const estimate = getCalibrationEstimate("staff_transition")!;
    render(<CalibrationPanel estimate={estimate} />);

    expect(screen.getByText("Calibrated")).toBeInTheDocument();
    expect(screen.getByText(String(estimate.sampleSize))).toBeInTheDocument();
    expect(screen.getByText(String(estimate.meanVariance))).toBeInTheDocument();
    expect(screen.getByText(String(estimate.stdevVariance))).toBeInTheDocument();
    expect(screen.getByText(estimate.confidenceBandNote!)).toBeInTheDocument();
  });

  it("renders a distinct, non-blank message when no calibration history exists at all", () => {
    render(<CalibrationPanel estimate={undefined} />);
    expect(screen.getByText(/no calibration history on file/i)).toBeInTheDocument();
  });

  it("the thin-history and calibrated states are visibly different, not the same markup with different numbers", () => {
    const thin = getCalibrationEstimate("relocation")!;
    const calibrated = getCalibrationEstimate("staff_transition")!;
    const { container: thinContainer } = render(<CalibrationPanel estimate={thin} />);
    const { container: calibratedContainer } = render(<CalibrationPanel estimate={calibrated} />);
    expect(thinContainer.innerHTML).not.toEqual(calibratedContainer.innerHTML);
  });
});
