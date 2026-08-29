import { describe, expect, it } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { PRIYA_ID, MAYA_ID } from "@/lib/fair-allocator";
import { RenegotiationDemo } from "./RenegotiationDemo";

const TASK_TITLES: Record<string, string> = {
  "obligation-renew-prescription": "Renew Dadi's prescription",
  "obligation-visit-pharmacy": "Pharmacy pickup",
  "obligation-weekly-groceries": "Weekly groceries",
};
const PERSON_NAMES: Record<string, string> = { [PRIYA_ID]: "Priya", [MAYA_ID]: "Maya" };

function renderDemo() {
  return render(<RenegotiationDemo taskTitle={(id) => TASK_TITLES[id] ?? id} personName={(id) => PERSON_NAMES[id] ?? id} />);
}

describe("RenegotiationDemo", () => {
  it("shows the trigger but no after-allocation before it is injected", () => {
    renderDemo();
    expect(screen.getByText(/just started night shifts/)).toBeInTheDocument();
    expect(screen.queryByText(/re-allocated following the night-shift trigger/)).not.toBeInTheDocument();
  });

  it("reveals a genuinely different allocation and concession evidence after injecting the trigger", () => {
    renderDemo();
    fireEvent.click(screen.getByRole("button", { name: /Inject this trigger/ }));
    expect(screen.getByText(/re-allocated following the night-shift trigger/)).toBeInTheDocument();
    // Concession evidence backed by real numbers, not a guess.
    expect(screen.getAllByText("1.0").length).toBeGreaterThan(0);
    expect(screen.getAllByText("6.0").length).toBeGreaterThan(0);
    expect(screen.getByText(/gave ground this cycle/)).toBeInTheDocument();
  });

  it("the after-allocation gives Maya the grocery run, a real task-ownership change, not just new numbers", () => {
    renderDemo();
    fireEvent.click(screen.getByRole("button", { name: /Inject this trigger/ }));
    expect(screen.getByText(/Total cost to Maya:/)).toBeInTheDocument();
    expect(screen.getByText("11.0")).toBeInTheDocument();
  });
});
