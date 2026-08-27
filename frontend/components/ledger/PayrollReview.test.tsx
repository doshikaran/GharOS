import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { getPayrollResults } from "@/lib/ledger";
import { PayrollReview, PayrollResultCard } from "./PayrollReview";

const { fetchDocumentRawMock } = vi.hoisted(() => ({ fetchDocumentRawMock: vi.fn() }));

vi.mock("@/lib/graph-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/graph-api")>("@/lib/graph-api");
  return { ...actual, fetchDocumentRaw: fetchDocumentRawMock };
});

describe("PayrollReview", () => {
  it("renders one card per payroll result", async () => {
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1]) });
    render(<PayrollReview results={getPayrollResults()} baseUrl="http://api.example" />);
    expect(screen.getByText("2026-08 payroll")).toBeInTheDocument();
    expect(screen.getByText("2026-07 payroll")).toBeInTheDocument();
  });

  it("shows the empty state when there are no payroll results", () => {
    render(<PayrollReview results={[]} baseUrl="http://api.example" />);
    expect(screen.getByText("No payroll cycles computed yet.")).toBeInTheDocument();
  });
});

describe("PayrollResultCard", () => {
  const clean = getPayrollResults().find((r) => !r.needsHumanReview)!;
  const needsReview = getPayrollResults().find((r) => r.needsHumanReview)!;

  it("renders the register image beside the computed figure for a clean result", async () => {
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1]) });
    render(<PayrollResultCard result={clean} baseUrl="http://api.example" />);

    await screen.findByRole("img", { name: /handwritten attendance register/ });
    // Every intermediate figure, not just the net total.
    expect(screen.getByText("₹9,000.00")).toBeInTheDocument();
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByText("No review needed")).toBeInTheDocument();
    expect(screen.queryByText("Needs human review")).not.toBeInTheDocument();
  });

  it("makes needs_human_review visually distinct and unmissable, with no guessed salary figure", async () => {
    fetchDocumentRawMock.mockRejectedValue(new Error("not found"));
    render(<PayrollResultCard result={needsReview} baseUrl="http://api.example" />);

    expect(screen.getByText("Needs human review")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(needsReview.reviewReason ?? "");
    expect(screen.getByText(/No computed salary figure yet/)).toBeInTheDocument();
    expect(screen.getByText(/Day 18/)).toBeInTheDocument();

    await waitFor(() => expect(screen.getByText(/Static placeholder/)).toBeInTheDocument());
  });
});
