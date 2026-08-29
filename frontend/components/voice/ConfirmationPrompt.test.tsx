import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ConfirmationPrompt } from "./ConfirmationPrompt";

describe("ConfirmationPrompt", () => {
  it("renders the read-back text prominently", () => {
    render(
      <ConfirmationPrompt
        prompt={{ type: "confirmation_prompt", text: "₹3,500, three thousand five hundred rupees to Om Electricals. Confirm?", requiresAffirmative: true, turnId: "t1" }}
        pendingApprovalCount={0}
      />,
    );
    expect(screen.getByText(/three thousand five hundred rupees/)).toBeInTheDocument();
  });

  it("states the explicit-affirmative rule and that silence/ambiguity is not approval", () => {
    render(
      <ConfirmationPrompt
        prompt={{ type: "confirmation_prompt", text: "Mark the maid absent today?", requiresAffirmative: true, turnId: "t2" }}
        pendingApprovalCount={0}
      />,
    );
    expect(screen.getByText(/not/i)).toBeInTheDocument();
    expect(screen.getByText(/Silence or an unclear reply/)).toBeInTheDocument();
  });

  it("renders no clickable affirm/decline button, the only real confirmation channel is spoken audio", () => {
    render(
      <ConfirmationPrompt
        prompt={{ type: "confirmation_prompt", text: "Confirm the appointment?", requiresAffirmative: true, turnId: "t3" }}
        pendingApprovalCount={0}
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the R3 visual-surface pointer, with the live pending count, when the read-back names a rupee amount", () => {
    render(
      <ConfirmationPrompt
        prompt={{ type: "confirmation_prompt", text: "Pay ₹3,500 to Om Electricals, confirm?", requiresAffirmative: true, turnId: "t4" }}
        pendingApprovalCount={2}
      />,
    );
    expect(screen.getByText(/will not move any money from your voice confirmation alone/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /confirm it in your Approvals tab/ })).toHaveAttribute("href", "/approvals");
    expect(screen.getByText(/you have 2 items waiting there now/)).toBeInTheDocument();
  });

  it("omits the money notice for a non-money confirmation", () => {
    render(
      <ConfirmationPrompt
        prompt={{ type: "confirmation_prompt", text: "Mark the maid absent today?", requiresAffirmative: true, turnId: "t5" }}
        pendingApprovalCount={0}
      />,
    );
    expect(screen.queryByText(/will not move any money/)).not.toBeInTheDocument();
  });

  it("is announced assertively, a missed confirmation is the highest-cost failure this surface can have", () => {
    render(
      <ConfirmationPrompt
        prompt={{ type: "confirmation_prompt", text: "Confirm?", requiresAffirmative: true, turnId: "t6" }}
        pendingApprovalCount={0}
      />,
    );
    expect(screen.getByRole("alert")).toHaveAttribute("aria-live", "assertive");
  });
});
