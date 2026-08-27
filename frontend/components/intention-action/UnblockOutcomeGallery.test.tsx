import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import {
  getDadiPhysioCandidates,
  getDentalCheckupModalitySwitch,
  getEyeCheckupInformationFetch,
  getFieldTripDecisionNarrowing,
} from "@/lib/intention-action";
import type { WindowFindingResult } from "@/lib/intention-action";
import { UnblockOutcomeGallery } from "./UnblockOutcomeGallery";

const windowOutcome: WindowFindingResult = {
  obligationId: "obligation-dadi-physio-escort",
  personId: "person-dadi",
  evaluations: [
    {
      window: getDadiPhysioCandidates()[3].window,
      personAvailability: "available",
      counterpartyAvailability: "available",
      historicalLikelihood: "likely",
      overallRecommended: true,
      reasoning: "Clear of everything on file.",
    },
    {
      window: getDadiPhysioCandidates()[0].window,
      personAvailability: "soft_avoid",
      counterpartyAvailability: null,
      historicalLikelihood: "unlikely",
      overallRecommended: false,
      reasoning: "Overlaps the nap window.",
    },
  ],
  bestWindow: getDadiPhysioCandidates()[3].window,
  confidence: 0.75,
  modelTier: "flash",
};

describe("UnblockOutcomeGallery", () => {
  it("renders the information blocker's real fetched fact as a before/after", () => {
    render(
      <UnblockOutcomeGallery
        informationOutcome={getEyeCheckupInformationFetch()}
        decisionOutcome={getFieldTripDecisionNarrowing()}
        aversionOutcome={getDentalCheckupModalitySwitch()}
        windowOutcome={windowOutcome}
        windowPersonName="Dadi"
      />,
    );
    const fetch = getEyeCheckupInformationFetch();
    expect(screen.getByText(fetch.factText as string)).toBeInTheDocument();
  });

  it("renders the decision blocker's two real, distinct options", () => {
    render(
      <UnblockOutcomeGallery
        informationOutcome={getEyeCheckupInformationFetch()}
        decisionOutcome={getFieldTripDecisionNarrowing()}
        aversionOutcome={getDentalCheckupModalitySwitch()}
        windowOutcome={windowOutcome}
        windowPersonName="Dadi"
      />,
    );
    const narrowing = getFieldTripDecisionNarrowing();
    expect(screen.getByTestId("decision-option-a")).toHaveTextContent(narrowing.optionA);
    expect(screen.getByTestId("decision-option-b")).toHaveTextContent(narrowing.optionB);
  });

  it("renders the aversion blocker's real modality switch and pre-drafted text", () => {
    render(
      <UnblockOutcomeGallery
        informationOutcome={getEyeCheckupInformationFetch()}
        decisionOutcome={getFieldTripDecisionNarrowing()}
        aversionOutcome={getDentalCheckupModalitySwitch()}
        windowOutcome={windowOutcome}
        windowPersonName="Dadi"
      />,
    );
    expect(screen.getByText("Phone call")).toBeInTheDocument();
    expect(screen.getByText("Written message")).toBeInTheDocument();
    expect(screen.getByText(/Hi Bright Smiles Dental/)).toBeInTheDocument();
  });

  it("renders the window blocker's real AvailabilityVerdict per candidate, including the recommended one", () => {
    render(
      <UnblockOutcomeGallery
        informationOutcome={getEyeCheckupInformationFetch()}
        decisionOutcome={getFieldTripDecisionNarrowing()}
        aversionOutcome={getDentalCheckupModalitySwitch()}
        windowOutcome={windowOutcome}
        windowPersonName="Dadi"
      />,
    );
    expect(screen.getByText("Dadi: Available")).toBeInTheDocument();
    expect(screen.getByText("Dadi: Soft — avoid if possible")).toBeInTheDocument();
    expect(screen.getByText("Recommended")).toBeInTheDocument();
  });

  it("shows an honest 'not fetched' message when the information outcome failed to resolve", () => {
    render(
      <UnblockOutcomeGallery
        informationOutcome={{ ...getEyeCheckupInformationFetch(), fetched: false, factText: null }}
        decisionOutcome={getFieldTripDecisionNarrowing()}
        aversionOutcome={getDentalCheckupModalitySwitch()}
        windowOutcome={windowOutcome}
        windowPersonName="Dadi"
      />,
    );
    expect(screen.getByText(/nothing was/)).toBeInTheDocument();
  });
});
