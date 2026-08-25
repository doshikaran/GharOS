import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ApprovalQueueItem } from "@/lib/approvals";
import { ApprovalCard } from "./ApprovalCard";

const NOW = new Date("2026-08-22T09:30:00Z");

function buildItem(overrides: Partial<ApprovalQueueItem> = {}): ApprovalQueueItem {
  return {
    id: "test-item",
    proposedActionSummary: "Pay the electrician ₹1,200 for the geyser repair.",
    riskTier: "R3",
    confidence: 0.85,
    consequenceIfWrong: "An incorrect payment cannot be recovered automatically.",
    status: "pending",
    expiresAt: "2026-08-23T09:00:00Z",
    evidenceBundle: {
      proposedAction: "Pay the electrician ₹1,200 for the geyser repair.",
      reasoning: "The invoice matches the completed obligation and no prior debit exists this cycle.",
      evidenceConsulted: ["Invoice photographed on completion", "No existing debit this cycle"],
      confidence: 0.85,
      consequenceIfWrong: "An incorrect payment cannot be recovered automatically.",
    },
    ...overrides,
  };
}

describe("ApprovalCard", () => {
  it("renders the proposed action, reasoning, evidence list, confidence, and consequence-if-wrong", () => {
    const item = buildItem();
    render(<ApprovalCard item={item} now={NOW} />);
    expect(screen.getByText(item.proposedActionSummary)).toBeInTheDocument();
    expect(screen.getByText(item.evidenceBundle.reasoning)).toBeInTheDocument();
    for (const entry of item.evidenceBundle.evidenceConsulted) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
    expect(screen.getByText("85%")).toBeInTheDocument();
    expect(screen.getByText(item.consequenceIfWrong)).toBeInTheDocument();
  });

  it("renders the risk tier with its real policy meaning, not just the code", () => {
    render(<ApprovalCard item={buildItem({ riskTier: "R3" })} now={NOW} />);
    expect(screen.getByText("R3 — Explicit approve")).toBeInTheDocument();
    expect(screen.getByText(/Any movement of money/)).toBeInTheDocument();
  });

  it("shows Approve and Reject for a pending, non-expired item and calls the right callback", () => {
    const onApprove = vi.fn();
    const onReject = vi.fn();
    render(<ApprovalCard item={buildItem()} onApprove={onApprove} onReject={onReject} now={NOW} />);

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(onApprove).toHaveBeenCalledWith("test-item");
    expect(onReject).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Reject" }));
    expect(onReject).toHaveBeenCalledWith("test-item");
  });

  it("never shows Approve/Reject for an R4 item, even if its status is 'pending'", () => {
    render(<ApprovalCard item={buildItem({ riskTier: "R4" })} now={NOW} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("renders an expired pending item as escalated — never as pending, never as approved", () => {
    const item = buildItem({ status: "pending", expiresAt: "2026-08-20T00:00:00Z" });
    render(<ApprovalCard item={item} now={NOW} />);
    expect(screen.getByText("Escalated")).toBeInTheDocument();
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(/escalated/i);
  });

  it("renders a status-flagged expired item as escalated too", () => {
    const item = buildItem({ status: "expired", expiresAt: "2026-08-20T00:00:00Z" });
    render(<ApprovalCard item={item} now={NOW} />);
    expect(screen.getByText("Escalated")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders an already-approved item with no action buttons and an explanatory note", () => {
    render(<ApprovalCard item={buildItem({ status: "approved" })} now={NOW} />);
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.getByText("Approved by a household member.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("renders an already-rejected item with no action buttons", () => {
    render(<ApprovalCard item={buildItem({ status: "rejected" })} now={NOW} />);
    expect(screen.getByText("Rejected")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("labels an auto-cleared R0/R1 item distinctly from a human-approved one", () => {
    const item = buildItem({ riskTier: "R1", status: "approved" });
    render(<ApprovalCard item={item} now={NOW} />);
    expect(screen.getByText(/Cleared automatically under R1/)).toBeInTheDocument();
  });
});
