import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { getApprovalQueue } from "@/lib/approvals";
import { EscalationSurface } from "./EscalationSurface";

const NOW = new Date("2026-08-22T09:30:00Z");

describe("EscalationSurface", () => {
  it("renders the R4 item under 'Council briefs'", () => {
    render(<EscalationSurface items={getApprovalQueue()} now={NOW} />);
    expect(
      screen.getByText("Whether to accept Sunrise Apartments Society's redevelopment buyback offer and relocate before the vacate deadline."),
    ).toBeInTheDocument();
    expect(screen.getByText("Council briefs, awaiting a household decision")).toBeInTheDocument();
  });

  it("renders the expired item under the expired-approvals section, not the Council-briefs section", () => {
    render(<EscalationSurface items={getApprovalQueue()} now={NOW} />);
    const expiredSection = screen.getByRole("region", { name: "Expired approvals" });
    expect(expiredSection).toHaveTextContent("Submit Aarav's school PTA volunteer sign-up form");
    const councilSection = screen.getByRole("region", { name: "Council briefs" });
    expect(councilSection).not.toHaveTextContent("Submit Aarav's school PTA volunteer sign-up form");
  });

  it("never shows an Approve or Reject button anywhere on the escalation surface", () => {
    render(<EscalationSurface items={getApprovalQueue()} now={NOW} />);
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
  });

  it("excludes pending R2/R3 and resolved items, only R4 and expired items appear", () => {
    render(<EscalationSurface items={getApprovalQueue()} now={NOW} />);
    expect(
      screen.queryByText("Call Om Electricals to confirm tomorrow's 4:00-5:00 PM slot to fix the geyser before Dadi's bath time."),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByText("Pay Sunrise Apartments Society's extended-deadline maintenance due of ₹2,500 for August via the registered mandate."),
    ).not.toBeInTheDocument();
  });

  it("shows an explicit empty state when nothing is escalated", () => {
    render(<EscalationSurface items={[]} now={NOW} />);
    expect(screen.getByText("Nothing is escalated right now.")).toBeInTheDocument();
  });

  it("forwards discussed-toggle state and callback through to each card", () => {
    const onToggle = vi.fn();
    render(
      <EscalationSurface
        items={getApprovalQueue()}
        now={NOW}
        discussedIds={new Set(["approval-redevelopment-buyback-brief"])}
        onToggleDiscussed={onToggle}
      />,
    );
    const switches = screen.getAllByRole("switch", { name: "Discussed with the household" });
    expect(switches[0]).toHaveAttribute("aria-checked", "true");
    fireEvent.click(switches[0]);
    expect(onToggle).toHaveBeenCalledWith("approval-redevelopment-buyback-brief", false);
  });
});
