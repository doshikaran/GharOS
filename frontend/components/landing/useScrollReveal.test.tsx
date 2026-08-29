import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen } from "@testing-library/react";
import { useScrollReveal } from "./useScrollReveal";

/**
 * jsdom does not implement `IntersectionObserver` — this fake captures the
 * callback each instance was constructed with so a test can fire it
 * manually, and records whether `disconnect()` was called (the hook must
 * reveal once and then stop observing, per its own docstring).
 */
class FakeIntersectionObserver implements IntersectionObserver {
  static instances: FakeIntersectionObserver[] = [];
  readonly root = null;
  readonly rootMargin = "";
  readonly thresholds: readonly number[] = [];

  constructor(public callback: IntersectionObserverCallback) {
    FakeIntersectionObserver.instances.push(this);
  }

  observe = vi.fn();
  unobserve = vi.fn();
  takeRecords = vi.fn(() => []);
  disconnect = vi.fn();

  fire(isIntersecting: boolean) {
    this.callback([{ isIntersecting } as IntersectionObserverEntry], this);
  }
}

function Probe() {
  const { ref, visible } = useScrollReveal<HTMLDivElement>();
  return (
    <div ref={ref} data-testid="probe">
      {visible ? "visible" : "hidden"}
    </div>
  );
}

describe("useScrollReveal", () => {
  const originalIO = globalThis.IntersectionObserver;

  beforeEach(() => {
    FakeIntersectionObserver.instances = [];
    globalThis.IntersectionObserver = FakeIntersectionObserver;
  });

  afterEach(() => {
    globalThis.IntersectionObserver = originalIO;
  });

  it("starts not visible", () => {
    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("hidden");
  });

  it("becomes visible once the observed element intersects, and disconnects (reveal-once)", () => {
    render(<Probe />);
    const observer = FakeIntersectionObserver.instances[0];
    expect(observer).toBeDefined();
    expect(observer.observe).toHaveBeenCalledWith(screen.getByTestId("probe"));

    act(() => {
      observer.fire(true);
    });

    expect(screen.getByTestId("probe")).toHaveTextContent("visible");
    expect(observer.disconnect).toHaveBeenCalledOnce();
  });

  it("does not reveal while not yet intersecting", () => {
    render(<Probe />);
    const observer = FakeIntersectionObserver.instances[0];

    act(() => {
      observer.fire(false);
    });

    expect(screen.getByTestId("probe")).toHaveTextContent("hidden");
    expect(observer.disconnect).not.toHaveBeenCalled();
  });

  it("falls back to immediately visible when IntersectionObserver is unavailable", () => {
    // @ts-expect-error -- deliberately simulating an unsupported environment
    globalThis.IntersectionObserver = undefined;

    render(<Probe />);
    expect(screen.getByTestId("probe")).toHaveTextContent("visible");
  });
});
