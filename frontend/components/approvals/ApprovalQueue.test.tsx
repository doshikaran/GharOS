import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { getApprovalQueue } from "@/lib/approvals";
import { ApprovalQueue } from "./ApprovalQueue";

const NOW = new Date("2026-08-22T09:30:00Z");

describe("ApprovalQueue", () => {
  it("renders R2/R3 pending items under 'Needs your decision' with working Approve/Reject", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(<ApprovalQueue items={getApprovalQueue()} onApprove={onApprove} onReject={onReject} now={NOW} />);

    expect(screen.getByText("Call Om Electricals to confirm tomorrow's 4:00-5:00 PM slot to fix the geyser before Dadi's bath time.")).toBeInTheDocument();
    expect(screen.getByText("Pay Kamala Bai's August salary of ₹14,000 via the registered UPI mandate.")).toBeInTheDocument();

    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]);
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("never renders any R4 item in the queue", () => {
    render(<ApprovalQueue items={getApprovalQueue()} now={NOW} />);
    expect(
      screen.queryByText("Whether to accept Sunrise Apartments Society's redevelopment buyback offer and relocate before the vacate deadline."),
    ).not.toBeInTheDocument();
  });

  it("never renders the expired item under 'Needs your decision'", () => {
    render(<ApprovalQueue items={getApprovalQueue()} now={NOW} />);
    const needsDecisionSection = screen.getByRole("region", { name: "Needs your decision" });
    expect(needsDecisionSection).not.toHaveTextContent("Submit Aarav's school PTA volunteer sign-up form");
  });

  it("renders already-approved and already-rejected items under 'Resolved', read-only", () => {
    render(<ApprovalQueue items={getApprovalQueue()} now={NOW} />);
    const resolvedSection = screen.getByRole("region", { name: "Resolved" });
    expect(resolvedSection).toHaveTextContent("Pay Sunrise Apartments Society's extended-deadline maintenance due");
    expect(resolvedSection).toHaveTextContent("Sunrise Apartments Society WhatsApp group disputing");
  });

  it("shows an explicit empty state when nothing is pending", () => {
    render(<ApprovalQueue items={[]} now={NOW} />);
    expect(screen.getByText("Nothing is awaiting approval right now.")).toBeInTheDocument();
    expect(screen.getByText("No resolved requests yet.")).toBeInTheDocument();
  });
});
