import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import type { GraphNode, GraphSnapshot } from "@/lib/graph-types";
import { GraphExplorer } from "./GraphExplorer";

/**
 * The live-growth-animation-driving test this phase's brief explicitly
 * requires: "write a test that mocks an EventSource-equivalent... delivering
 * a node event after initial render and asserts the new node is added to
 * rendered state, distinct from initial nodes."
 *
 * `GraphExplorer` renders the canvas (which needs `ResizeObserver` /
 * `requestAnimationFrame` / a 2D context polyfilled — none exist in jsdom),
 * so this file carries the same canvas polyfills as `GraphCanvas.test.tsx`.
 * The actual assertions, though, go through the accessible sr-only node
 * list `GraphExplorer` renders alongside the canvas (`data-testid`
 * `"graph-node-list"`) — canvas content has no DOM/ARIA representation to
 * assert against directly, and that list is the deliberate, real
 * accessibility affordance (screen readers cannot read canvas pixels)
 * that doubles as this test's seam.
 */

class FakeResizeObserver {
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

/** A hand-driveable fake `EventSource` — captures every constructed
 * instance so the test can reach in and dispatch a synthetic frame,
 * exactly like `lib/graph-stream.test.ts`'s `FakeEventSource` but built as
 * a real global `EventSource` replacement since `GraphExplorer` uses
 * `subscribeToGraphStream`'s default (real) factory. */
class FakeEventSource {
  static instances: FakeEventSource[] = [];
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  constructor(public url: string) {
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {}

  dispatch(type: string, data: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(data) } as MessageEvent);
    }
  }
}

const baselineNode: GraphNode = {
  id: "obligation-baseline",
  type: "OBLIGATION",
  label: "Pay maintenance",
  derivation: "extracted",
  confidence: 0.9,
  source_document_id: null,
  region: null,
  created_at: "2026-08-20T00:00:00Z",
  fields: {},
};

const liveNode: GraphNode = {
  id: "obligation-live",
  type: "OBLIGATION",
  label: "Confirm geyser repair slot",
  derivation: "extracted",
  confidence: 0.85,
  source_document_id: null,
  region: null,
  created_at: "2026-08-22T09:00:00Z",
  fields: {},
};

const RECT = { width: 800, height: 600, top: 0, left: 0, right: 800, bottom: 600, x: 0, y: 0, toJSON: () => ({}) } as DOMRect;

describe("GraphExplorer, live growth via the graph stream", () => {
  beforeEach(() => {
    FakeEventSource.instances = [];
    vi.stubGlobal("ResizeObserver", FakeResizeObserver);
    vi.stubGlobal("requestAnimationFrame", () => 1);
    vi.stubGlobal("cancelAnimationFrame", vi.fn());
    vi.stubGlobal("EventSource", FakeEventSource);
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue(RECT);
    vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(
      createFakeContext() as unknown as CanvasRenderingContext2D,
    );

    const snapshot: GraphSnapshot = { nodes: [baselineNode], edges: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(snapshot) } as Response),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
    cleanup();
  });

  it("renders the baseline snapshot node un-flagged (never treated as a live arrival)", async () => {
    render(<GraphExplorer baseUrl="http://api.example" />);

    await waitFor(() => expect(screen.getByTestId("graph-node-list")).toBeInTheDocument());
    const list = screen.getByTestId("graph-node-list");
    const item = within(list).getByText(/Pay maintenance/);
    expect(item.closest("li")).toHaveAttribute("data-arrived-live", "false");
    expect(within(list).getAllByRole("listitem")).toHaveLength(1);
  });

  it("only subscribes to the stream after the baseline snapshot has loaded", async () => {
    render(<GraphExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    expect(FakeEventSource.instances[0].url).toBe("http://api.example/graph/stream");
  });

  it("a node event delivered after initial render is added to rendered state, distinct from the initial node", async () => {
    render(<GraphExplorer baseUrl="http://api.example" />);

    await waitFor(() => expect(FakeEventSource.instances).toHaveLength(1));
    const source = FakeEventSource.instances[0];

    source.dispatch("node", liveNode);

    const list = screen.getByTestId("graph-node-list");
    await waitFor(() => expect(within(list).getAllByRole("listitem")).toHaveLength(2));

    const baselineItem = within(list).getByText(/Pay maintenance/).closest("li");
    const liveItem = within(list).getByText(/Confirm geyser repair slot/).closest("li");

    // The distinguishing assertion this test exists for: the streamed node
    // is flagged as a live arrival; the snapshot node still isn't.
    expect(baselineItem).toHaveAttribute("data-arrived-live", "false");
    expect(liveItem).toHaveAttribute("data-arrived-live", "true");
  });

  it("shows a real error rather than a blank graph when the snapshot fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    render(<GraphExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load the graph/));
  });
});
