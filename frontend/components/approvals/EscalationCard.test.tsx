import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ApprovalQueueItem } from "@/lib/approvals";
import { EscalationCard } from "./EscalationCard";

const NOW = new Date("2026-08-22T09:30:00Z");

function buildR4Item(overrides: Partial<ApprovalQueueItem> = {}): ApprovalQueueItem {
  return {
    id: "test-r4",
    proposedActionSummary: "Whether to accept the redevelopment buyback offer and relocate.",
    riskTier: "R4",
    confidence: 0.71,
    consequenceIfWrong: "Either error is largely irreversible and affects every household member.",
    status: "pending",
    expiresAt: "2026-09-21T09:00:00Z",
    evidenceBundle: {
      proposedAction: "Whether to accept the redevelopment buyback offer and relocate.",
      reasoning: "This is irreversible and emotionally loaded — the Council produces a brief, not a decision.",
      evidenceConsulted: ["Redevelopment notice sets a 90-day vacate deadline", "Care specialist flags mobility"],
      confidence: 0.71,
      consequenceIfWrong: "Either error is largely irreversible and affects every household member.",
    },
    ...overrides,
  };
}

function buildExpiredItem(overrides: Partial<ApprovalQueueItem> = {}): ApprovalQueueItem {
  return {
    id: "test-expired",
    proposedActionSummary: "Submit the PTA volunteer sign-up form.",
    riskTier: "R2",
    confidence: 0.8,
    consequenceIfWrong: "Aarav's class may go unrepresented unless someone re-raises it.",
    status: "expired",
    expiresAt: "2026-08-22T06:00:00Z",
    evidenceBundle: {
      proposedAction: "Submit the PTA volunteer sign-up form.",
      reasoning: "The approval window closed with no decision.",
      evidenceConsulted: ["School WhatsApp thread requests volunteers by a fixed deadline"],
      confidence: 0.8,
      consequenceIfWrong: "Aarav's class may go unrepresented unless someone re-raises it.",
    },
    ...overrides,
  };
}

describe("EscalationCard", () => {
  it("renders an R4 item as a Council brief, never as an approve/reject item", () => {
    render(<EscalationCard item={buildR4Item()} now={NOW} />);
    expect(screen.getByText("Council brief — humans decide")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Reject" })).not.toBeInTheDocument();
    expect(screen.getByText(/Council never resolves it/)).toBeInTheDocument();
  });

  it("never uses the word 'debate' for the R4 Council-brief explainer", () => {
    render(<EscalationCard item={buildR4Item()} now={NOW} />);
    expect(screen.queryByText(/debate/i)).not.toBeInTheDocument();
  });

  it("renders the full evidence bundle for an R4 brief", () => {
    const item = buildR4Item();
    render(<EscalationCard item={item} now={NOW} />);
    expect(screen.getByText(item.evidenceBundle.reasoning)).toBeInTheDocument();
    for (const entry of item.evidenceBundle.evidenceConsulted) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
  });

  it("renders an expired item as escalated, distinctly from approved or pending, with no Approve/Reject", () => {
    render(<EscalationCard item={buildExpiredItem()} now={NOW} />);
    expect(screen.getByText("Escalated — approval window expired")).toBeInTheDocument();
    expect(screen.queryByText("Approved")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(screen.getByText(/has not been approved, and it has not been rejected/)).toBeInTheDocument();
  });

  it("exposes a 'discussed with the household' toggle that is explicitly not an approval action", () => {
    const onToggle = vi.fn();
    render(<EscalationCard item={buildR4Item()} now={NOW} onToggleDiscussed={onToggle} />);
    expect(
      screen.getByText("This only tracks whether the household has talked this through — it does not approve, reject, or execute anything."),
    ).toBeInTheDocument();

    fireEvent.click(screen.getByRole("switch", { name: "Discussed with the household" }));
    expect(onToggle).toHaveBeenCalledWith("test-r4", true);
  });
});
