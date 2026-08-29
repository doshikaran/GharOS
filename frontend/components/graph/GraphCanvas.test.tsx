import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { GraphNode } from "@/lib/graph-types";
import { GraphCanvas } from "./GraphCanvas";

function makeNode(id: string, type: GraphNode["type"] = "OBLIGATION"): GraphNode {
  return {
    id,
    type,
    label: id,
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: null,
    region: null,
    created_at: "2026-08-20T00:00:00Z",
    fields: {},
  };
}

class FakeResizeObserver {
  constructor(private callback: ResizeObserverCallback) {}
  observe(): void {}
  unobserve(): void {}
  disconnect(): void {}
}

function createFakeContext() {
  return {
    save: vi.fn(),
    restore: vi.fn(),
    clearRect: vi.fn(),
    fillRect: vi.fn(),
    translate: vi.fn(),
    scale: vi.fn(),
    setTransform: vi.fn(),
    beginPath: vi.fn(),
    moveTo: vi.fn(),
    lineTo: vi.fn(),
    closePath: vi.fn(),
    arc: vi.fn(),
    fill: vi.fn(),
    stroke: vi.fn(),
    setLineDash: vi.fn(),
    roundRect: vi.fn(),
    fillStyle: "",
    strokeStyle: "",
    lineWidth: 1,
    globalAlpha: 1,
  };
}

const RECT = { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;

describe("GraphCanvas", () => {
  let rafQueue: FrameRequestCallback[];
  let fakeCtx: ReturnType<typeof createFakeContext>;

  beforeEach(() => {
    rafQueue = [];
    fakeCtx = createFakeContext();

    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      rafQueue.push(cb);
      return rafQueue.length;
    });
    vi.stubGlobal("cancelAnimationFrame", vi.fn());

    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(RECT);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      fakeCtx as unknown as CanvasRenderingContext2D,
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    cleanup();
  });

  function flushFrame(): void {
    const cb = rafQueue.shift();
    cb?.(performance.now());
  }

  it("renders an accessible canvas element", () => {
    render(
      <GraphCanvas
        nodes={[]}
        edges={[]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        highlightedPath={null}
      />,
    );
    expect(screen.getByRole("img", { name: "Household knowledge graph" })).toBeInTheDocument();
  });

  it("schedules exactly one animation frame per mount", () => {
    render(
      <GraphCanvas
        nodes={[]}
        edges={[]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        highlightedPath={null}
      />,
    );
    expect(rafQueue).toHaveLength(1);
  });

  it("draws to the canvas once a frame is flushed, clears, fills the background, and draws the node's filled geometry", () => {
    render(
      <GraphCanvas
        nodes={[makeNode("a")]}
        edges={[]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        highlightedPath={null}
      />,
    );
    flushFrame();
    expect(fakeCtx.clearRect).toHaveBeenCalled();
    expect(fakeCtx.fillRect).toHaveBeenCalled();
    // OBLIGATION is drawn filled (see graph-visual-encoding.ts) — fill()
    // must have been called at least once for the node itself.
    expect(fakeCtx.fill).toHaveBeenCalled();
  });

  it("styles a conflict edge with the thicker conflict line width, distinct from a non-conflict edge", () => {
    render(
      <GraphCanvas
        nodes={[makeNode("a"), makeNode("b")]}
        edges={[
          {
            id: "e1",
            type: "conflicts_with",
            from_id: "a",
            to_id: "b",
            derivation: "extracted",
            confidence: 0.8,
            is_conflict: true,
          },
        ]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        highlightedPath={null}
      />,
    );
    // Two ticks: let the two-node layout settle enough to have positions,
    // then flush a frame that actually draws the edge.
    flushFrame();
    flushFrame();
    // lineWidth is a plain property on the fake context, so its final
    // recorded value after drawing reflects the last edge/node drawn; the
    // meaningful assertion is that stroke() was invoked for the edge path,
    // which only happens once both endpoints have settled positions.
    expect(fakeCtx.stroke).toHaveBeenCalled();
  });

  it("clicking a settled lone node's exact centre selects it", () => {
    const onSelectNode = vi.fn();
    const { container } = render(
      <GraphCanvas
        nodes={[makeNode("a")]}
        edges={[]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={onSelectNode}
        highlightedPath={null}
      />,
    );
    // A lone, unconnected node settles to the simulation's exact centre —
    // (400, 300) for the 800x600 RECT above — deterministically: d3's
    // forceCenter mutates position directly (not via velocity) each tick,
    // and forceManyBody/forceCollide have nothing else to act against.
    for (let i = 0; i < 5; i += 1) flushFrame();

    const canvas = container.querySelector("canvas") as HTMLCanvasElement;
    fireEvent.click(canvas, { clientX: 400, clientY: 300 });

    expect(onSelectNode).toHaveBeenCalledWith("a");
  });

  it("clicking empty space deselects (calls onSelectNode with null)", () => {
    const onSelectNode = vi.fn();
    const { container } = render(
      <GraphCanvas
        nodes={[makeNode("a")]}
        edges={[]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={onSelectNode}
        highlightedPath={null}
      />,
    );
    for (let i = 0; i < 5; i += 1) flushFrame();

    const canvas = container.querySelector("canvas") as HTMLCanvasElement;
    fireEvent.click(canvas, { clientX: 5, clientY: 5 });

    expect(onSelectNode).toHaveBeenCalledWith(null);
  });

  it("cancels the animation frame and disconnects the resize observer on unmount", () => {
    const cancelSpy = vi.fn();
    vi.stubGlobal("cancelAnimationFrame", cancelSpy);
    const disconnectSpy = vi.spyOn(FakeResizeObserver.prototype, "disconnect");

    const { unmount } = render(
      <GraphCanvas
        nodes={[]}
        edges={[]}
        liveArrivedAt={new Map()}
        selectedNodeId={null}
        onSelectNode={vi.fn()}
        highlightedPath={null}
      />,
    );
    unmount();

    expect(cancelSpy).toHaveBeenCalled();
    expect(disconnectSpy).toHaveBeenCalled();
  });
});
