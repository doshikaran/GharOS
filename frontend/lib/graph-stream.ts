/**
 * `GET /graph/stream` client — Server-Sent Events, live mutations only,
 * never a replay of existing state (`/graph/snapshot` covers the baseline —
 * see `lib/graph-api.ts`). Every event delivered here is a genuinely new
 * arrival: this is the only place the live growth animation is triggered
 * from (Phase 6 brief — "the one place motion carries meaning").
 *
 * Built against an injectable `EventSource`-equivalent rather than the
 * global `window.EventSource` directly, so tests can supply a fake source
 * that dispatches synthetic `node`/`edge` events without a real network
 * connection or a real SSE parser.
 */

import type { GraphEdge, GraphNode } from "./graph-types";

export type GraphStreamEvent =
  | { readonly kind: "node"; readonly node: GraphNode }
  | { readonly kind: "edge"; readonly edge: GraphEdge };

/** The minimal shape of the browser `EventSource` this module depends on —
 * small enough that a test fake can implement it directly. */
export interface EventSourceLike {
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  removeEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}

export type EventSourceFactory = (url: string) => EventSourceLike;

const defaultEventSourceFactory: EventSourceFactory = (url) =>
  new EventSource(url) as unknown as EventSourceLike;

export interface GraphStreamHandlers {
  onEvent(event: GraphStreamEvent): void;
  /** Called with the raw error if a `node`/`edge` payload fails to parse as
   * JSON, or the underlying source reports a connection error. Never
   * throws past this boundary — a malformed frame is reported, not a crash. */
  onError?(error: Error): void;
}

/**
 * Subscribes to `{baseUrl}/graph/stream` and calls `handlers.onEvent` for
 * every `event: node` / `event: edge` SSE frame received from this point
 * forward. Returns an unsubscribe function that closes the connection.
 *
 * @param baseUrl - the API's base URL (see `getApiBaseUrl`).
 * @param handlers - callbacks for each parsed event and for errors.
 * @param createEventSource - factory for the underlying source, injectable
 *   for tests; defaults to the real browser `EventSource`.
 */
export function subscribeToGraphStream(
  baseUrl: string,
  handlers: GraphStreamHandlers,
  createEventSource: EventSourceFactory = defaultEventSourceFactory,
): () => void {
  const source = createEventSource(`${baseUrl}/graph/stream`);

  const handleNode = (event: MessageEvent) => {
    try {
      const node = JSON.parse(event.data as string) as GraphNode;
      handlers.onEvent({ kind: "node", node });
    } catch (err) {
      handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const handleEdge = (event: MessageEvent) => {
    try {
      const edge = JSON.parse(event.data as string) as GraphEdge;
      handlers.onEvent({ kind: "edge", edge });
    } catch (err) {
      handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
    }
  };

  const handleConnectionError = () => {
    handlers.onError?.(new Error("graph stream connection error"));
  };

  source.addEventListener("node", handleNode);
  source.addEventListener("edge", handleEdge);
  source.addEventListener("error", handleConnectionError);

  return () => {
    source.removeEventListener("node", handleNode);
    source.removeEventListener("edge", handleEdge);
    source.removeEventListener("error", handleConnectionError);
    source.close();
  };
}
