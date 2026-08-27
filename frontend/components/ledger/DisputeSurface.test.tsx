import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getDisputePresentations } from "@/lib/ledger";
import { DisputeCard, DisputeSurface } from "./DisputeSurface";

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 }).format(amount);
}

describe("DisputeSurface", () => {
  it("renders one card per dispute", () => {
    render(<DisputeSurface disputes={getDisputePresentations()} />);
    expect(screen.getByText("August society maintenance debit")).toBeInTheDocument();
    expect(screen.getByText("Maya's August salary payment")).toBeInTheDocument();
  });

  it("shows the empty state when there are no open disputes", () => {
    render(<DisputeSurface disputes={[]} />);
    expect(screen.getByText("No open disputes right now.")).toBeInTheDocument();
  });
});

describe("DisputeCard", () => {
  const dispute = getDisputePresentations()[0];

  it("renders both figures with their source labels, amounts, and evidence", () => {
    render(<DisputeCard dispute={dispute} />);
    expect(screen.getByText(dispute.figureA.sourceLabel)).toBeInTheDocument();
    expect(screen.getByText(dispute.figureB.sourceLabel)).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(dispute.figureA.amount, dispute.figureA.currency))).toBeInTheDocument();
    expect(screen.getByText(formatCurrency(dispute.figureB.amount, dispute.figureB.currency))).toBeInTheDocument();
  });

  it("renders both figures with the same DOM structure — neither side gets special markup", () => {
    render(<DisputeCard dispute={dispute} />);
    const figureCards = screen.getAllByTestId("conflicting-figure");
    expect(figureCards).toHaveLength(2);
    expect(figureCards[0].className).toBe(figureCards[1].className);
  });

  it("shows the neutral discrepancy amount and context", () => {
    render(<DisputeCard dispute={dispute} />);
    expect(screen.getByText("Context")).toBeInTheDocument();
    expect(screen.getByText(dispute.context)).toBeInTheDocument();
    expect(screen.getByText(/Discrepancy:/)).toBeInTheDocument();
  });

  it("never renders a resolve, choose, or accept affordance anywhere", () => {
    render(<DisputeCard dispute={dispute} />);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("radio")).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByText(/correct figure/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/we (think|believe)/i)).not.toBeInTheDocument();
  });

  it("shows the escalated-to-human badge", () => {
    render(<DisputeCard dispute={dispute} />);
    expect(screen.getByText(/Escalated to human resolution/)).toBeInTheDocument();
  });
});
