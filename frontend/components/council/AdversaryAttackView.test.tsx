import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { getCouncilBrief } from "@/lib/council";
import { AdversaryAttackView } from "./AdversaryAttackView";

describe("AdversaryAttackView", () => {
  it("renders the real critique text and every cited outcome id", () => {
    const brief = getCouncilBrief();
    render(<AdversaryAttackView attack={brief.adversaryAttack} />);

    expect(screen.getByText(brief.adversaryAttack.critique)).toBeInTheDocument();
    for (const outcomeId of brief.adversaryAttack.citedOutcomeIds) {
      expect(screen.getByText(outcomeId)).toBeInTheDocument();
    }
  });

  it("frames itself as an attack on the leading option, not a sixth position", () => {
    const brief = getCouncilBrief();
    render(<AdversaryAttackView attack={brief.adversaryAttack} />);
    expect(screen.getByText(/attacking the leading option — not a position/i)).toBeInTheDocument();
  });

  it('never renders the word "debate"', () => {
    const brief = getCouncilBrief();
    render(<AdversaryAttackView attack={brief.adversaryAttack} />);
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });
});
