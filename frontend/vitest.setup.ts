import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";
import "@testing-library/jest-dom/vitest";

// Explicit cleanup: this project does not enable Vitest's `globals` mode,
// so @testing-library/react's automatic afterEach-based cleanup (which
// relies on detecting a global `afterEach`) never registers on its own.
afterEach(() => {
  cleanup();
});

/**
 * jsdom ships no `EventSource`. Most SSE code in this repo takes an
 * injectable factory (`lib/graph-stream.ts`, `lib/voice-session.ts`,
 * `lib/mic-capture.ts`), but `subscribeToGraphStream`'s *default* factory
 * calls the global `new EventSource(url)` directly. `GraphExplorer`/
 * `ConnectionsExplorer` tests `vi.stubGlobal("EventSource", Fake)` for the
 * duration of a test and then `vi.unstubAllGlobals()` — which, when the
 * key had no prior value, *deletes* it. Under a loaded parallel run a
 * component effect can fire its `subscribeToGraphStream` call one tick
 * after that teardown, hit the now-missing global, and throw a bare
 * `ReferenceError: EventSource is not defined` that the runner then
 * attributes to whichever test is unlucky enough to be in scope.
 *
 * Installing an inert, spec-shaped `EventSource` here removes that whole
 * failure class: it is the value `unstubAllGlobals` restores to, so a
 * late default-factory call becomes a harmless no-op connection (correct
 * behaviour for a test environment with no SSE server) instead of a
 * crash. Tests that need to *drive* a stream still stub their own fake
 * over the top of it exactly as before.
 */
class InertEventSource extends EventTarget {
  static readonly CONNECTING = 0;
  static readonly OPEN = 1;
  static readonly CLOSED = 2;

  readonly CONNECTING = InertEventSource.CONNECTING;
  readonly OPEN = InertEventSource.OPEN;
  readonly CLOSED = InertEventSource.CLOSED;

  readonly url: string;
  readonly withCredentials: boolean;
  readyState: number = InertEventSource.CONNECTING;
  onopen: ((this: EventSource, ev: Event) => unknown) | null = null;
  onmessage: ((this: EventSource, ev: MessageEvent) => unknown) | null = null;
  onerror: ((this: EventSource, ev: Event) => unknown) | null = null;

  constructor(url: string | URL, init?: { withCredentials?: boolean }) {
    super();
    this.url = String(url);
    this.withCredentials = init?.withCredentials ?? false;
    // Never opens a connection: no network in jsdom, and nothing here
    // should be exercising a real SSE endpoint.
  }

  close(): void {
    this.readyState = InertEventSource.CLOSED;
  }
}

if (typeof globalThis.EventSource === "undefined") {
  Object.defineProperty(globalThis, "EventSource", {
    value: InertEventSource,
    writable: true,
    configurable: true,
  });
}
