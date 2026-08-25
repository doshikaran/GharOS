import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { EvidenceBundle } from "@/lib/approvals";
import { EvidenceBundleView } from "./EvidenceBundleView";

const bundle: EvidenceBundle = {
  proposedAction: "Pay Kamala Bai's August salary of ₹14,000 via the registered UPI mandate.",
  reasoning: "The attendance register matches the agreed monthly rate for this cycle.",
  evidenceConsulted: [
    "Handwritten payroll register photographed 21 Aug",
    "Household HR note: agreed monthly rate ₹14,000",
    "Ledger check: no existing debit this cycle",
  ],
  confidence: 0.93,
  consequenceIfWrong: "Underpaying shorts a household employee; overpaying is an unrecoverable transfer.",
};

describe("EvidenceBundleView", () => {
  it("renders the reasoning in full", () => {
    render(<EvidenceBundleView bundle={bundle} />);
    expect(screen.getByText(bundle.reasoning)).toBeInTheDocument();
  });

  it("renders every evidence-consulted entry as a real list item — none truncated or hidden", () => {
    render(<EvidenceBundleView bundle={bundle} />);
    for (const entry of bundle.evidenceConsulted) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
    expect(screen.getAllByRole("listitem")).toHaveLength(bundle.evidenceConsulted.length);
    expect(screen.getByText(`Evidence consulted (${bundle.evidenceConsulted.length})`)).toBeInTheDocument();
  });

  it("renders confidence visually via ConfidenceMeter, not just as a raw number", () => {
    render(<EvidenceBundleView bundle={bundle} />);
    expect(screen.getByRole("progressbar")).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument();
  });

  it("renders the consequence-if-wrong in full", () => {
    render(<EvidenceBundleView bundle={bundle} />);
    expect(screen.getByText(bundle.consequenceIfWrong)).toBeInTheDocument();
  });
});
