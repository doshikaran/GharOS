import { describe, expect, it } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import { getApprovalQueue } from "@/lib/approvals";
import { ApprovalsBoard } from "./ApprovalsBoard";

const NOW = new Date("2026-08-22T09:30:00Z");

describe("ApprovalsBoard", () => {
  it("shows a live summary of how many items need a decision, are escalated, and are resolved", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    // Fixture: 2 pending needing approval (R2 call, R3 salary), 2 escalated
    // (R4 brief, expired PTA form), 4 resolved (R0, R1, R2 rejected, R3 approved).
    expect(screen.getByRole("status")).toHaveTextContent("2 need your decision · 2 escalated · 4 resolved");
  });

  it("never executes an approval on the queue's Approve click alone — it opens a confirm dialog first", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    const approveButtons = screen.getAllByRole("button", { name: "Approve" });
    fireEvent.click(approveButtons[0]);

    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Confirm approval — this executes now");
    // Still pending — nothing executed yet.
    expect(screen.getByRole("status")).toHaveTextContent("2 need your decision");
  });

  it("restates the full evidence bundle inside the confirm dialog before execution", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);

    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Call Om Electricals/)).toBeInTheDocument();
    expect(within(dialog).getByRole("progressbar")).toBeInTheDocument();
  });

  it("only executes the approval after the explicit 'Confirm and execute' click inside the dialog", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm and execute" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 need your decision · 2 escalated · 5 resolved");
  });

  it("treats closing the dialog (Cancel) as no consent — the item stays pending", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 need your decision · 2 escalated · 4 resolved");
  });

  it("treats pressing Escape on the confirm dialog as no consent too", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Approve" })[0]);
    fireEvent.keyDown(document, { key: "Escape" });

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("2 need your decision · 2 escalated · 4 resolved");
  });

  it("rejects immediately on click — no confirm dialog required for the safe direction", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[0]);

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("1 need your decision · 2 escalated · 5 resolved");
  });

  it("lets the household toggle 'discussed' on an escalation card without approving or executing anything", () => {
    render(<ApprovalsBoard initialItems={getApprovalQueue()} now={NOW} />);
    const toggle = screen.getAllByRole("switch", { name: "Discussed with the household" })[0];
    expect(toggle).toHaveAttribute("aria-checked", "false");

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-checked", "true");
    // Toggling discussed never changes the decision counts.
    expect(screen.getByRole("status")).toHaveTextContent("2 need your decision · 2 escalated · 4 resolved");
  });
});
