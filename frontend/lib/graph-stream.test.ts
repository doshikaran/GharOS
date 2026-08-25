import { describe, expect, it, vi } from "vitest";
import { subscribeToGraphStream, type EventSourceLike } from "./graph-stream";
import type { GraphNode } from "./graph-types";

/** A minimal fake `EventSourceLike` a test can drive by hand — no real
 * network connection or SSE parser involved. */
class FakeEventSource implements EventSourceLike {
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();
  closed = false;

  addEventListener(type: string, listener: (event: MessageEvent) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void): void {
    this.listeners.get(type)?.delete(listener);
  }

  close(): void {
    this.closed = true;
  }

  dispatch(type: string, data: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: JSON.stringify(data) } as MessageEvent);
    }
  }

  dispatchRaw(type: string, rawData: string): void {
    for (const listener of this.listeners.get(type) ?? []) {
      listener({ data: rawData } as MessageEvent);
    }
  }
}

const sampleNode: GraphNode = {
  id: "obligation-1",
  type: "OBLIGATION",
  label: "Pay maintenance",
  derivation: "extracted",
  confidence: 0.9,
  source_document_id: "doc-1",
  region: "0-10",
  created_at: "2026-08-20T00:00:00Z",
  fields: {},
};

describe("subscribeToGraphStream", () => {
  it("hits the /graph/stream URL via the injected factory", () => {
    const fake = new FakeEventSource();
    const factory = vi.fn().mockReturnValue(fake);
    subscribeToGraphStream("http://api.example", { onEvent: () => {} }, factory);
    expect(factory).toHaveBeenCalledWith("http://api.example/graph/stream");
  });

  it("delivers a parsed node event to onEvent", () => {
    const fake = new FakeEventSource();
    const onEvent = vi.fn();
    subscribeToGraphStream("http://api.example", { onEvent }, () => fake);

    fake.dispatch("node", sampleNode);

    expect(onEvent).toHaveBeenCalledWith({ kind: "node", node: sampleNode });
  });

  it("delivers a parsed edge event to onEvent", () => {
    const fake = new FakeEventSource();
    const onEvent = vi.fn();
    subscribeToGraphStream("http://api.example", { onEvent }, () => fake);

    const edge = { id: "e1", type: "implies", from_id: "a", to_id: "b", derivation: "extracted", confidence: 0.8, is_conflict: false };
    fake.dispatch("edge", edge);

    expect(onEvent).toHaveBeenCalledWith({ kind: "edge", edge });
  });

  it("reports a parse error via onError instead of throwing, for a malformed frame", () => {
    const fake = new FakeEventSource();
    const onEvent = vi.fn();
    const onError = vi.fn();
    subscribeToGraphStream("http://api.example", { onEvent, onError }, () => fake);

    expect(() => fake.dispatchRaw("node", "{not valid json")).not.toThrow();
    expect(onEvent).not.toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });

  it("reports a connection error via onError", () => {
    const fake = new FakeEventSource();
    const onError = vi.fn();
    subscribeToGraphStream("http://api.example", { onEvent: () => {}, onError }, () => fake);

    fake.dispatch("error", null);

    expect(onError).toHaveBeenCalledWith(expect.any(Error));
  });

  it("closes the source and stops delivering events once unsubscribed", () => {
    const fake = new FakeEventSource();
    const onEvent = vi.fn();
    const unsubscribe = subscribeToGraphStream("http://api.example", { onEvent }, () => fake);

    unsubscribe();
    expect(fake.closed).toBe(true);

    fake.dispatch("node", sampleNode);
    expect(onEvent).not.toHaveBeenCalled();
  });
});
