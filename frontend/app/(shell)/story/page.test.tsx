import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import Home from "./page";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

class FakeIntersectionObserver implements IntersectionObserver {
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds: readonly number[] = [];
  constructor(public callback: IntersectionObserverCallback) {}
  observe = vi.fn();
  unobserve = vi.fn();
  takeRecords = vi.fn(() => []);
  disconnect = vi.fn();
}

/**
 * Extracts the "Invariant" column of `PHASES.md` Appendix B's table,
 * straight from the source file, so this test fails the moment the
 * landing page's copy drifts from the actual safety-invariant wording —
 * a hardcoded duplicate list here would defeat the "verbatim, not
 * paraphrased" requirement the redesign brief calls out explicitly.
 */
function readSafetyInvariantsFromPhasesDoc(): string[] {
  const phasesDoc = readFileSync(path.join(__dirname, "../../../../PHASES.md"), "utf-8");
  const sectionStart = phasesDoc.indexOf("## APPENDIX B — SAFETY INVARIANT SCHEDULE");
  const sectionEnd = phasesDoc.indexOf("## APPENDIX C", sectionStart);
  const section = phasesDoc.slice(sectionStart, sectionEnd);

  return section
    .split("\n")
    .filter((line) => /^\|\s*\d+\s*\|/.test(line))
    .map((line) => line.split("|")[2]?.trim())
    .filter((cell): cell is string => Boolean(cell));
}

describe("Home (landing page)", () => {
  beforeEach(() => {
    globalThis.IntersectionObserver = FakeIntersectionObserver;
  });

  afterEach(() => {
    // @ts-expect-error -- restore to "undefined" (jsdom's real absence)
    globalThis.IntersectionObserver = undefined;
  });

  it("renders all six sections", () => {
    render(<Home />);

    expect(screen.getByRole("heading", { name: /the household remembers/i, level: 1 })).toBeInTheDocument();
    expect(screen.getByText(/somewhere between a whatsapp message/i)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /the answer is a path, not a vibe/i })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "The journey" })).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /built on real infrastructure/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /this isn.t a dashboard/i }),
    ).toBeInTheDocument();
  });

  it("renders the nine journey chapters, in order", () => {
    render(<Home />);
    const expected = [
      "Perception",
      "Consequence Engine",
      "Arbitration",
      "Household Ledger",
      "Fair Allocator",
      "Intention → Action",
      "Outbound Concierge",
      "Household Simulator",
      "Household Council",
    ];
    const journeyList = screen.getByTestId("journey-list");
    const chapterHeadings = within(journeyList)
      .getAllByRole("heading", { level: 3 })
      .map((el) => el.textContent);
    expect(chapterHeadings).toEqual(expected);
  });

  it("uses the real, already-shipped DerivationBadge component for the insight section (not a mockup)", () => {
    render(<Home />);
    // DerivationBadge's own rendered labels (DerivationBadge.tsx's LABEL map).
    expect(screen.getByText("Extracted")).toBeInTheDocument();
    expect(screen.getByText("Inferred")).toBeInTheDocument();
    expect(screen.getByText("Ambiguous")).toBeInTheDocument();
    // DerivationBadge's own data attribute, proving it's the real component
    // and not a hand-rolled lookalike.
    expect(screen.getByText("Extracted").closest("[data-derivation]")).toHaveAttribute(
      "data-derivation",
      "extracted",
    );
  });

  it("carries the proof section's safety-invariant list verbatim from PHASES.md Appendix B", () => {
    render(<Home />);
    const invariantsFromDoc = readSafetyInvariantsFromPhasesDoc();

    expect(invariantsFromDoc).toHaveLength(8);
    for (const invariant of invariantsFromDoc) {
      expect(screen.getByText(invariant)).toBeInTheDocument();
    }
  });

  it("links both the hero and closing CTA to /graph", () => {
    render(<Home />);
    const graphLinks = screen.getAllByRole("link", { name: /enter the graph|enter gharos/i });
    expect(graphLinks.length).toBeGreaterThanOrEqual(2);
    for (const link of graphLinks) {
      expect(link).toHaveAttribute("href", "/graph");
    }
  });
});
