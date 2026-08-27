import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getFairnessVerificationResult, PRIYA_ID, MAYA_ID } from "@/lib/fair-allocator";
import { PersonShareExplanations } from "./PersonShareExplanations";

const TASK_TITLES: Record<string, string> = {
  "obligation-renew-prescription": "Renew Dadi's prescription",
  "obligation-visit-pharmacy": "Pharmacy pickup",
  "obligation-weekly-groceries": "Weekly groceries",
};
const PERSON_NAMES: Record<string, string> = { [PRIYA_ID]: "Priya", [MAYA_ID]: "Maya" };

function renderExplanations() {
  const { explanations } = getFairnessVerificationResult("before");
  return render(
    <PersonShareExplanations
      explanations={explanations}
      personName={(id) => PERSON_NAMES[id] ?? id}
      taskTitle={(id) => TASK_TITLES[id] ?? id}
    />,
  );
}

describe("PersonShareExplanations", () => {
  it("renders one card per person with their own tasks", () => {
    renderExplanations();
    expect(screen.getByRole("heading", { name: "Priya" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Maya" })).toBeInTheDocument();
    expect(screen.getAllByText("Weekly groceries").length).toBeGreaterThan(0);
    expect(screen.getByText("Renew Dadi's prescription")).toBeInTheDocument();
    expect(screen.getByText("Pharmacy pickup")).toBeInTheDocument();
  });

  it("each explanation is distinct — never a generic sentence interchangeable between people", () => {
    renderExplanations();
    const { explanations } = getFairnessVerificationResult("before");
    const texts = explanations.map((e) => e.explanationText);
    expect(new Set(texts).size).toBe(texts.length);
    // Each explanation must actually name that person's own tasks/costs, not a template.
    expect(texts[0]).toContain("1.0");
    expect(texts[1]).toContain("4.0");
  });

  it("renders a real confidence meter per explanation", () => {
    renderExplanations();
    expect(screen.getAllByRole("progressbar")).toHaveLength(2);
  });

  it("renders a real, honest empty state with no explanations", () => {
    render(<PersonShareExplanations explanations={[]} personName={(id) => id} taskTitle={(id) => id} />);
    expect(screen.getByText(/No per-person explanations/)).toBeInTheDocument();
  });
});
