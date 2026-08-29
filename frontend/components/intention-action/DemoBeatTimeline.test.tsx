import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  DENTAL_CHECKUP_RESOLUTION_SECONDS,
  getDentalCheckupAttempts,
  getDentalCheckupModalitySwitch,
  getDentalCheckupWindow,
  getStaleObligationDetection,
} from "@/lib/intention-action";
import { DemoBeatTimeline } from "./DemoBeatTimeline";

describe("DemoBeatTimeline", () => {
  it("renders the real days-stale figure as the 'before'", () => {
    render(
      <DemoBeatTimeline
        stale={getStaleObligationDetection()}
        attemptCount={getDentalCheckupAttempts().length}
        modalitySwitch={getDentalCheckupModalitySwitch()}
        windowResult={getDentalCheckupWindow()}
        resolutionSeconds={DENTAL_CHECKUP_RESOLUTION_SECONDS}
      />,
    );
    expect(screen.getByTestId("stale-days")).toHaveTextContent("124 days untouched");
    expect(screen.getByText("3 failed unblocking attempts")).toBeInTheDocument();
  });

  it("renders the real 'after' chain: diagnosed, unblocked, scheduled", () => {
    render(
      <DemoBeatTimeline
        stale={getStaleObligationDetection()}
        attemptCount={getDentalCheckupAttempts().length}
        modalitySwitch={getDentalCheckupModalitySwitch()}
        windowResult={getDentalCheckupWindow()}
        resolutionSeconds={DENTAL_CHECKUP_RESOLUTION_SECONDS}
      />,
    );
    expect(screen.getByText(/call switched to message/)).toBeInTheDocument();
    expect(screen.getByText(/Scheduled, Saturday, 29 Aug/)).toBeInTheDocument();
  });

  it("renders the real resolution-seconds figure", () => {
    render(
      <DemoBeatTimeline
        stale={getStaleObligationDetection()}
        attemptCount={getDentalCheckupAttempts().length}
        modalitySwitch={getDentalCheckupModalitySwitch()}
        windowResult={getDentalCheckupWindow()}
        resolutionSeconds={DENTAL_CHECKUP_RESOLUTION_SECONDS}
      />,
    );
    expect(screen.getByTestId("resolution-seconds")).toHaveTextContent("Resolved in 30 seconds");
  });

  it("renders honestly when no window was found", () => {
    const windowResult = { ...getDentalCheckupWindow(), bestWindow: null };
    render(
      <DemoBeatTimeline
        stale={getStaleObligationDetection()}
        attemptCount={getDentalCheckupAttempts().length}
        modalitySwitch={getDentalCheckupModalitySwitch()}
        windowResult={windowResult}
        resolutionSeconds={DENTAL_CHECKUP_RESOLUTION_SECONDS}
      />,
    );
    expect(screen.getByText(/no window found/)).toBeInTheDocument();
  });
});
