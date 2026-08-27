import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getLeakageCases } from "@/lib/ledger";
import { LeakageCaseCard, LeakageRecoverySurface } from "./LeakageRecoverySurface";

describe("LeakageRecoverySurface", () => {
  it("renders one card per leakage case", () => {
    render(<LeakageRecoverySurface cases={getLeakageCases()} />);
    // Card headings (not the drafted-claim body text, which for at least one
    // case also happens to repeat the commitment's label).
    expect(screen.getByRole("heading", { name: /CloudTV Premium/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Fit Circle Gym membership/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /SpeedLink Fiber broadband/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Mehta Pharmacy home-delivery plan/ })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /Sunrise Society Diwali event fund/ })).toBeInTheDocument();
  });

  it("shows the empty state when there are no cases", () => {
    render(<LeakageRecoverySurface cases={[]} />);
    expect(screen.getByText("No leakage findings on file yet.")).toBeInTheDocument();
  });
});

describe("LeakageCaseCard", () => {
  const cloudtv = getLeakageCases().find((c) => c.request.commitmentId === "commitment-cloudtv-premium")!;
  const worthKeeping = getLeakageCases().find((c) => c.finding.verdict === "worth_keeping")!;

  it("renders the verdict, reasoning, and usage evidence", () => {
    render(<LeakageCaseCard leakageCase={cloudtv} />);
    expect(screen.getByText("Leakage")).toBeInTheDocument();
    expect(screen.getByText(cloudtv.finding.reasoning)).toBeInTheDocument();
    expect(screen.getByText("No recorded usage on file")).toBeInTheDocument();
  });

  it("renders the drafted claim read-only, with no send affordance anywhere", () => {
    render(<LeakageCaseCard leakageCase={cloudtv} />);
    expect(screen.getByText(cloudtv.recoveryDraft!.ask)).toBeInTheDocument();
    expect(screen.getByText(cloudtv.recoveryDraft!.messageText)).toBeInTheDocument();
    expect(screen.getByText(/never sent automatically/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /send/i })).not.toBeInTheDocument();
  });

  it("shows 'no claim drafted' for a worth_keeping verdict with no RecoveryDraft", () => {
    render(<LeakageCaseCard leakageCase={worthKeeping} />);
    expect(screen.getByText("No claim drafted for this commitment.")).toBeInTheDocument();
  });

  it("renders a confidence meter reflecting the finding's real confidence", () => {
    render(<LeakageCaseCard leakageCase={cloudtv} />);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", String(Math.round(cloudtv.finding.confidence * 100)));
  });
});
