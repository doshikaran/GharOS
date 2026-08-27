import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import type { SalaryCalculationResult } from "@/lib/ledger";
import { SalaryFigureBreakdown } from "./SalaryFigureBreakdown";

const salary: SalaryCalculationResult = {
  staffPersonId: "person-maya",
  month: "2026-08",
  currency: "INR",
  daysWorked: 22,
  daysAbsent: 2,
  daysOnLeaveUnpaid: 1,
  dailyRate: 500,
  grossAmount: 11000,
  totalAdvancesDeducted: 2000,
  advanceEventIds: ["ledger-maya-advance"],
  netSalaryDue: 9000,
  flooredAtZero: false,
};

describe("SalaryFigureBreakdown", () => {
  it("renders every intermediate figure, not just the net total", () => {
    render(<SalaryFigureBreakdown salary={salary} />);
    expect(screen.getByText("22")).toBeInTheDocument();
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();
    expect(screen.getByText("₹500.00")).toBeInTheDocument();
    expect(screen.getByText("₹11,000.00")).toBeInTheDocument();
    expect(screen.getByText("₹9,000.00")).toBeInTheDocument();
  });

  it("shows the real advance LedgerEvent id backing the deduction, for audit", () => {
    render(<SalaryFigureBreakdown salary={salary} />);
    expect(screen.getByText(/ledger-maya-advance/)).toBeInTheDocument();
  });

  it("shows the floored-at-zero badge only when it actually happened", () => {
    render(<SalaryFigureBreakdown salary={salary} />);
    expect(screen.queryByText(/Floored at zero/)).not.toBeInTheDocument();

    const flooredSalary: SalaryCalculationResult = { ...salary, netSalaryDue: 0, flooredAtZero: true, totalAdvancesDeducted: 12000 };
    render(<SalaryFigureBreakdown salary={flooredSalary} />);
    expect(screen.getByText(/Floored at zero/)).toBeInTheDocument();
  });
});
