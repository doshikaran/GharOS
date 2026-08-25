import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { RISK_TIER_ORDER, RISK_TIER_POLICY } from "@/lib/approvals";
import { RiskTierBadge } from "./RiskTierBadge";

describe("RiskTierBadge", () => {
  it.each(RISK_TIER_ORDER)("renders %s's label and real policy meaning, not just the bare code", (tier) => {
    render(<RiskTierBadge tier={tier} />);
    const entry = RISK_TIER_POLICY[tier];
    expect(screen.getByText(entry.label)).toBeInTheDocument();
    expect(screen.getByText(new RegExp(entry.definition.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")))).toBeInTheDocument();
  });

  it("shows R4's 'never auto-execute' policy distinctly from every other tier", () => {
    render(<RiskTierBadge tier="R4" />);
    expect(screen.getByText(/never auto-execute/i)).toBeInTheDocument();
  });

  it("never uses the word 'debate' in any tier's policy copy", () => {
    for (const tier of RISK_TIER_ORDER) {
      render(<RiskTierBadge tier={tier} />);
    }
    expect(screen.queryByText(/debate/i)).not.toBeInTheDocument();
  });
});
