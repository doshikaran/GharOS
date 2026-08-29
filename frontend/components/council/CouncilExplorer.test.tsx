import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { render, screen, within } from "@testing-library/react";
import { getCouncilBrief } from "@/lib/council";
import { CouncilExplorer } from "./CouncilExplorer";

const COUNCIL_DIR = dirname(fileURLToPath(import.meta.url));

/** Every non-test source file directly under `components/council/` — the
 * "component tree" this phase's brief names. Test files are excluded
 * deliberately: every sibling `*.test.tsx` in this directory legitimately
 * contains the literal string "debate" as the banned value it asserts
 * *against* (`.not.toContain("debate")`), which is meta-commentary about
 * the rule, not a use of debate-framing in shipped copy — scanning them
 * would make this test fail against its own siblings' safety checks. */
function councilTreeSourceFiles(): readonly string[] {
  return readdirSync(COUNCIL_DIR)
    .filter((name) => (name.endsWith(".ts") || name.endsWith(".tsx") || name.endsWith(".css")) && !name.includes(".test."))
    .map((name) => join(COUNCIL_DIR, name));
}

describe("CouncilExplorer", () => {
  it("renders the convening question, trigger, and who was convened", () => {
    render(<CouncilExplorer />);
    const brief = getCouncilBrief();
    expect(screen.getAllByText(brief.question).length).toBeGreaterThan(0);
    expect(screen.getByText(/rising trend/i)).toBeInTheDocument();
  });

  it("renders specialist positions naming genuinely different subgraphs, not generic prose", () => {
    render(<CouncilExplorer />);
    const positionsSection = screen.getByRole("list", { name: "Specialist positions" });
    expect(within(positionsSection).getByText(/Finance: Ledger subgraph/)).toBeInTheDocument();
    expect(within(positionsSection).getByText(/Care: Constraint subgraph/)).toBeInTheDocument();
    expect(within(positionsSection).getByText(/₹34,500/)).toBeInTheDocument();
    expect(within(positionsSection).getByText(/constraint-dadi-mobility/)).toBeInTheDocument();
  });

  it("renders eliminated options in their own struck-through section, distinct from surviving options named separately", () => {
    render(<CouncilExplorer />);
    const struckText = document.querySelector("s");
    expect(struckText?.textContent).toMatch(/hatchback/i);
    // The surviving set is named in its own note, and does not include the
    // struck-through hatchback.
    expect(screen.getByText(/Surviving options carried into scoring/)).toBeInTheDocument();
    const survivingNote = screen.getByText(/Surviving options carried into scoring/);
    expect(survivingNote.textContent?.toLowerCase()).not.toContain("hatchback");
  });

  it("renders delegate scores attributed to real named people", () => {
    render(<CouncilExplorer />);
    expect(screen.getByText("Priya")).toBeInTheDocument();
    expect(screen.getByText("Maya")).toBeInTheDocument();
    expect(screen.getByText("Dadi")).toBeInTheDocument();
  });

  it("renders the adversary's attack in a distinct section citing real outcome ids, never folded in with specialist positions", () => {
    render(<CouncilExplorer />);
    const brief = getCouncilBrief();
    expect(screen.getByText(/not a position/i)).toBeInTheDocument();
    for (const outcomeId of brief.adversaryAttack.citedOutcomeIds) {
      expect(screen.getByText(outcomeId)).toBeInTheDocument();
    }
  });

  it("renders the explicit trade-off with real people and real regret numbers, never a bare number dump", () => {
    render(<CouncilExplorer />);
    const brief = getCouncilBrief();
    const costlyRegret = brief.resolution.regretByPerson[brief.resolution.mostCostlyTo!].toFixed(1);
    expect(screen.getByText(new RegExp(`regret of ${costlyRegret}`))).toBeInTheDocument();
    expect(screen.getByText(/maximises joint welfare|minimax-regret pick/i)).toBeInTheDocument();
  });

  it("renders the risk register as a flat, scannable list", () => {
    render(<CouncilExplorer />);
    const brief = getCouncilBrief();
    for (const entry of brief.riskRegister) {
      expect(screen.getByText(entry)).toBeInTheDocument();
    }
  });

  it("never implies the household must accept the arbiter's resolution, no concrete verdict-issuing phrase appears", () => {
    render(<CouncilExplorer />);
    const text = document.body.textContent?.toLowerCase() ?? "";
    // Concrete instruction-to-comply phrases, not the bare words this
    // page's own honest disclaimer legitimately uses ("brief, not a
    // verdict" explains the system never issues one — a bare-word ban
    // would falsely fail against that very disclaimer).
    for (const phrase of [
      "you must choose",
      "the household should pick",
      "the household must",
      "this is the final decision",
      "you should choose",
      "must accept",
    ]) {
      expect(text).not.toContain(phrase);
    }
    // And the disclaimer itself is actually present.
    expect(text).toContain("humans decide");
    expect(screen.getByText(/nothing below executes an action, moves money, or places a call/i)).toBeInTheDocument();
  });

  it('never renders the word "debate" anywhere in its rendered output', () => {
    render(<CouncilExplorer />);
    expect(document.body.textContent?.toLowerCase()).not.toContain("debate");
  });

  it('the literal word "debate" (case-insensitive) appears nowhere in this component tree\'s own source files', () => {
    const files = councilTreeSourceFiles();
    expect(files.length).toBeGreaterThan(10);
    for (const file of files) {
      const content = readFileSync(file, "utf-8");
      expect(content.toLowerCase(), `${file} must never contain the word "debate"`).not.toContain("debate");
    }
  });
});
