import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { getAaravToothacheApproval } from "@/lib/concierge";
import { CallApprovalGate } from "./CallApprovalGate";

describe("CallApprovalGate", () => {
  it("renders the full evidence bundle and risk tier before any decision", () => {
    const approval = getAaravToothacheApproval();
    render(<CallApprovalGate approval={approval} approved={false} onApprove={() => {}} />);
    expect(screen.getByText(approval.evidenceBundle.proposedAction)).toBeInTheDocument();
    expect(screen.getByText(approval.evidenceBundle.reasoning)).toBeInTheDocument();
    for (const evidence of approval.evidenceBundle.evidenceConsulted) {
      expect(screen.getByText(evidence)).toBeInTheDocument();
    }
    expect(screen.getByText("Awaiting decision")).toBeInTheDocument();
  });

  it("calls onApprove exactly once when the approve button is clicked", () => {
    const approval = getAaravToothacheApproval();
    const onApprove = vi.fn();
    render(<CallApprovalGate approval={approval} approved={false} onApprove={onApprove} />);
    fireEvent.click(screen.getByRole("button", { name: /approve this call/i }));
    expect(onApprove).toHaveBeenCalledTimes(1);
  });

  it("shows an approved state with no approve button once approved is true", () => {
    const approval = getAaravToothacheApproval();
    render(<CallApprovalGate approval={approval} approved onApprove={() => {}} />);
    expect(screen.getByText("Approved")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /approve this call/i })).not.toBeInTheDocument();
  });
});
