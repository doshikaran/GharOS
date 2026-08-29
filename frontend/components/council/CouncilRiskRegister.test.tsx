import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getCouncilBrief } from "@/lib/council";
import { CouncilRiskRegister } from "./CouncilRiskRegister";

describe("CouncilRiskRegister", () => {
  it("renders every risk register entry as its own flat, scannable row", () => {
    const brief = getCouncilBrief();
    render(<CouncilRiskRegister entries={brief.riskRegister} />);

    const list = screen.getByRole("list", { name: "Risk register" });
    expect(list.children).toHaveLength(brief.riskRegister.length);
    for (const entry of brief.riskRegister) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
  });

  it("renders an honest empty state when the brief raised no risks", () => {
    render(<CouncilRiskRegister entries={[]} />);
    expect(screen.getByText(/No risks raised on this brief/)).toBeInTheDocument();
  });

  it('never renders the word "debate"', () => {
    const brief = getCouncilBrief();
    render(<CouncilRiskRegister entries={brief.riskRegister} />);
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
