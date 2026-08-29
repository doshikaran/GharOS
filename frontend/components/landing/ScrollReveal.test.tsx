import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import { ScrollReveal } from "./ScrollReveal";

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

describe("ScrollReveal", () => {
  const originalIO = globalThis.IntersectionObserver;

  beforeEach(() => {
    globalThis.IntersectionObserver = FakeIntersectionObserver;
  });

  afterEach(() => {
    globalThis.IntersectionObserver = originalIO;
  });

  it("renders its children as the requested tag", () => {
    render(
      <ScrollReveal as="section" index={2}>
        <p>Chapter content</p>
      </ScrollReveal>,
    );
    expect(screen.getByText("Chapter content")).toBeInTheDocument();
  });

  it("applies a stagger delay proportional to its index, via --reveal-stagger", () => {
    render(
      <ScrollReveal as="section" index={3} className="chapter">
        <p>Staggered</p>
      </ScrollReveal>,
    );
    const el = screen.getByText("Staggered").closest("section") as HTMLElement;
    expect(el.style.transitionDelay).toBe("calc(3 * var(--reveal-stagger))");
  });

  it("starts with data-visible=false before intersecting", () => {
    render(
      <ScrollReveal as="div">
        <span>x</span>
      </ScrollReveal>,
    );
    const el = screen.getByText("x").closest("div") as HTMLElement;
    expect(el.getAttribute("data-visible")).toBe("false");
  });

  it("declares a prefers-reduced-motion override that fully neutralizes the reveal animation (no animation, content just appears)", () => {
    // Source-level check rather than a computed-style assertion: jsdom does
    // not reliably evaluate @media-gated cascade for prefers-reduced-motion,
    // so this reads the actual shipped CSS and asserts the escape hatch is
    // present and complete — the same real-proof-not-eyeballed standard
    // this project's own tokens.css comments hold themselves to.
    const css = readFileSync(path.join(__dirname, "ScrollReveal.module.css"), "utf-8");

    expect(css).toContain("@media (prefers-reduced-motion: reduce)");

    const reducedMotionBlock = css.slice(css.indexOf("@media (prefers-reduced-motion: reduce)"));
    expect(reducedMotionBlock).toContain("opacity: 1");
    expect(reducedMotionBlock).toContain("transform: none");
    expect(reducedMotionBlock).toContain("transition: none");
  });
});
