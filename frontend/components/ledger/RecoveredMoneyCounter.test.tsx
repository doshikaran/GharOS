import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { RecoveredMoneySummary } from "@/lib/ledger";
import { RecoveredMoneyCounter } from "./RecoveredMoneyCounter";

describe("RecoveredMoneyCounter", () => {
  it("renders the demo metric's exact structure: found ₹X/year of leakage, N claims drafted", () => {
    const summary: RecoveredMoneySummary = {
      annualLeakageTotal: 33588,
      currency: "INR",
      draftsAwaitingApproval: 3,
      leakageCaseCount: 3,
    };
    render(<RecoveredMoneyCounter summary={summary} />);
    const headline = screen.getByRole("status");
    expect(headline).toHaveTextContent("Found");
    expect(headline).toHaveTextContent("/year");
    expect(headline).toHaveTextContent("of leakage");
    expect(headline).toHaveTextContent("3");
    expect(headline).toHaveTextContent("claims drafted, awaiting approval");
    expect(headline).toHaveTextContent("₹33,588");
  });

  it("uses singular phrasing for exactly one drafted claim", () => {
    const summary: RecoveredMoneySummary = {
      annualLeakageTotal: 5988,
      currency: "INR",
      draftsAwaitingApproval: 1,
      leakageCaseCount: 1,
    };
    render(<RecoveredMoneyCounter summary={summary} />);
    expect(screen.getByRole("status")).toHaveTextContent("1 claim drafted, awaiting approval");
  });

  it("renders zero honestly rather than hiding the counter when nothing has been found yet", () => {
    const summary: RecoveredMoneySummary = { annualLeakageTotal: 0, currency: "INR", draftsAwaitingApproval: 0, leakageCaseCount: 0 };
    render(<RecoveredMoneyCounter summary={summary} />);
    expect(screen.getByRole("status")).toHaveTextContent("₹0/year");
    expect(screen.getByRole("status")).toHaveTextContent("0 claims drafted");
  });
});
