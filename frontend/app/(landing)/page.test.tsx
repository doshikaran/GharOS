import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import {
  LANDING_APPROVAL_ITEM,
  LANDING_CONFIRMATION_PROMPT,
} from "@/components/landing/landingFixtures";
import LandingLayout from "./layout";
import Landing from "./page";

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

/** Installs a `matchMedia` that reports reduced motion as `matches`. */
function stubMatchMedia(reduceMatches: boolean): void {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: query === "(prefers-reduced-motion: reduce)" ? reduceMatches : false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  }));
}

describe("Landing (standalone `/` page, 2026-08-29 private-bank pass)", () => {
  beforeEach(() => {
    globalThis.IntersectionObserver = FakeIntersectionObserver;
  });

  afterEach(() => {
    // @ts-expect-error -- restore to "undefined" (jsdom's real absence)
    globalThis.IntersectionObserver = undefined;
    // @ts-expect-error -- jsdom has no matchMedia by default; restore that
    window.matchMedia = undefined;
    document.documentElement.removeAttribute("data-theme");
  });

  it("renders standalone — no AppShell chrome anywhere on the page", () => {
    render(<Landing />);
    expect(screen.queryByRole("navigation")).toBeNull();
    // Sidebar-only labels from navConfig must not leak onto the landing.
    expect(screen.queryByText("Household Graph")).toBeNull();
    expect(screen.queryByText("System Status")).toBeNull();
  });

  it("landing layout renders a minimal header (wordmark + Open app → /graph), not the AppShell", () => {
    render(
      <LandingLayout params={Promise.resolve({})}>
        <p>page body</p>
      </LandingLayout>,
    );
    expect(screen.getByRole("banner")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "GharOS" })).toHaveAttribute("href", "/");
    expect(screen.getByRole("link", { name: "Open app" })).toHaveAttribute("href", "/graph");
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByText("Household Graph")).toBeNull();
    expect(screen.getByText("page body")).toBeInTheDocument();
  });

  it("both CTAs say what happens and link to /graph", () => {
    render(<Landing />);
    const ctas = screen.getAllByRole("link", { name: "Get started" });
    expect(ctas).toHaveLength(2);
    for (const cta of ctas) {
      expect(cta).toHaveAttribute("href", "/graph");
    }
  });

  it("links to the full story at /story from the footer", () => {
    render(<Landing />);
    expect(screen.getByRole("link", { name: /the full story/i })).toHaveAttribute("href", "/story");
  });

  describe("hero device — the three scrubbed states, rendered from the REAL components", () => {
    it("state 1: the code-mixed transcript with per-span language tags", () => {
      render(<Landing />);
      // LanguageSpanChip renders each span's own text and language label.
      expect(screen.getByText("Society maintenance")).toBeInTheDocument();
      expect(screen.getByText("ka payment karna hai")).toBeInTheDocument();
      expect(screen.getByText("English")).toBeInTheDocument();
      expect(screen.getByText("Hindi")).toBeInTheDocument();
      // SessionStateIndicator's real "listening" register.
      expect(screen.getByText("Listening")).toBeInTheDocument();
    });

    it("state 2: the full read-back register, amount repeated in words", () => {
      render(<Landing />);
      expect(screen.getByText(LANDING_CONFIRMATION_PROMPT.text)).toBeInTheDocument();
    });

    it("state 3: the real approval card — R3, pending, evidence bundle attached", () => {
      render(<Landing />);
      // The card's own title is the proposed-action summary; unique to the
      // ApprovalCard (EvidenceBundleView never renders it itself).
      expect(screen.getByText(LANDING_APPROVAL_ITEM.proposedActionSummary)).toBeInTheDocument();
      // "Awaiting decision" is ApprovalCard's pending status badge.
      expect(screen.getByText("Awaiting decision")).toBeInTheDocument();
      // The R3 policy label appears twice: on the device card and in the
      // worked narrative's own RiskTierBadge.
      expect(screen.getAllByText("R3 — Explicit approve").length).toBeGreaterThanOrEqual(2);
    });

    it("starts the scrub on state 1", () => {
      const { container } = render(<Landing />);
      const first = container.querySelector('[data-device-state="0"]');
      const second = container.querySelector('[data-device-state="1"]');
      expect(first).toHaveAttribute("data-active", "true");
      expect(second).toHaveAttribute("data-active", "false");
    });
  });

  it("under prefers-reduced-motion, composes statically around the read-back state only", () => {
    stubMatchMedia(true);
    render(<Landing />);
    // Only state 2 (the read-back) is rendered at all.
    expect(screen.getByText(LANDING_CONFIRMATION_PROMPT.text)).toBeInTheDocument();
    expect(screen.queryByText("Society maintenance")).toBeNull();
    expect(screen.queryByText(LANDING_APPROVAL_ITEM.proposedActionSummary)).toBeNull();
  });

  it("carries the worked narrative's four steps, in order, as one transaction", () => {
    render(<Landing />);
    const narrative = screen.getByTestId("worked-narrative");
    const stepTitles = within(narrative)
      .getAllByRole("heading", { level: 3 })
      .map((el) => el.textContent);
    expect(stepTitles).toEqual([
      "A message arrives",
      "An obligation is inferred",
      "Queued for approval",
      "Approved by a person",
    ]);
    // The inferred obligation uses the real DerivationBadge, not a mockup.
    expect(screen.getByText("Inferred").closest("[data-derivation]")).toHaveAttribute(
      "data-derivation",
      "inferred",
    );
  });

  it("lists the four things it will never do", () => {
    render(<Landing />);
    for (const line of [
      "Money reasoners hold no money tools.",
      "Nothing sends without approval.",
      "Voice alone never moves money.",
      "Every fact shows its source.",
    ]) {
      expect(screen.getByText(line)).toBeInTheDocument();
    }
  });

  it("renders under both themes without forcing either (tokens do the theming)", () => {
    for (const theme of ["light", "dark"] as const) {
      document.documentElement.setAttribute("data-theme", theme);
      const { container, unmount } = render(<Landing />);
      expect(
        screen.getByRole("heading", { name: /the household remembers/i, level: 1 }),
      ).toBeInTheDocument();
      // Nothing inside the page pins its own data-theme — the page must
      // follow the viewer's theme, not force one.
      expect(container.querySelector("[data-theme]")).toBeNull();
      unmount();
    }
  });
});
