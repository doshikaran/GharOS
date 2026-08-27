import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getFairAllocationResult, getEf1Violations, PRIYA_ID, MAYA_ID } from "@/lib/fair-allocator";
import { AllocationResult } from "./AllocationResult";

const TASK_TITLES: Record<string, string> = {
  "obligation-renew-prescription": "Renew Dadi's prescription",
  "obligation-visit-pharmacy": "Pharmacy pickup",
  "obligation-weekly-groceries": "Weekly groceries",
};
const PERSON_NAMES: Record<string, string> = { [PRIYA_ID]: "Priya", [MAYA_ID]: "Maya" };

function renderResult(scenario: "before" | "after") {
  return render(
    <AllocationResult
      result={getFairAllocationResult(scenario)}
      violations={getEf1Violations(scenario)}
      taskTitle={(id) => TASK_TITLES[id] ?? id}
      personName={(id) => PERSON_NAMES[id] ?? id}
    />,
  );
}

describe("AllocationResult", () => {
  it("states EF1 with the precise term and a plain-language gloss, never 'optimal'", () => {
    renderResult("before");
    expect(screen.getByText(/Envy-free up to one item \(EF1\) — holds/)).toBeInTheDocument();
    expect(screen.getAllByText(/verify_ef1/).length).toBeGreaterThan(0);
    expect(document.body.textContent?.toLowerCase()).not.toContain("optimal");
    expect(document.body.textContent?.toLowerCase()).not.toMatch(/\bfairest\b/);
  });

  it("renders each person's own bundle and total cost", () => {
    renderResult("before");
    expect(screen.getByRole("heading", { name: "Priya" })).toBeInTheDocument();
    expect(screen.getAllByText("Weekly groceries").length).toBeGreaterThan(0);
    expect(screen.getByText(/Total cost to Priya:/)).toBeInTheDocument();
    expect(screen.getAllByText("1.0").length).toBeGreaterThan(0);
  });

  it("renders the full pick trail with turn, round, person, task, and cost", () => {
    renderResult("before");
    const rows = screen.getAllByRole("row");
    // header + 3 picks
    expect(rows).toHaveLength(4);
  });

  it("shows a different allocation for the after scenario", () => {
    renderResult("after");
    expect(screen.getByText(/Total cost to Maya:/)).toBeInTheDocument();
    expect(screen.getByText("11.0")).toBeInTheDocument();
  });
});
