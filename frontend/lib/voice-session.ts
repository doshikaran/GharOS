"use client";

import { parseVoiceServerEvent, type VoiceServerEvent } from "./voice-types";

/** `WebSocket.OPEN`'s numeric value, per the spec — named here so no call
 * site compares `readyState` against a magic `1`. */
const WEBSOCKET_OPEN_STATE = 1;

/**
 * Minimal shape of the browser `WebSocket` this module depends on, small
 * enough for a test fake to implement directly — same injectable-factory
 * discipline as `lib/graph-stream.ts`'s `EventSourceLike`.
 */
export interface WebSocketLike {
  readonly readyState: number;
  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void;
  close(code?: number, reason?: string): void;
  /** One non-overloaded signature rather than four per-event-type
   * overloads — overload sets are awkward for a plain test fake to
   * satisfy structurally; every real call site here either ignores the
   * event (open/close/error) or reads it as a `MessageEvent`
   * (message), both of which this single signature covers. */
  addEventListener(type: "open" | "message" | "close" | "error", listener: (event: MessageEvent) => void): void;
}

export type WebSocketFactory = (url: string) => WebSocketLike;

function defaultWebSocketFactory(url: string): WebSocketLike {
  return new WebSocket(url) as unknown as WebSocketLike;
}

/** The session endpoint path, ADR-020 Decision 3. */
export const VOICE_SESSION_PATH = "/voice/session";

/** Rewrites an `http(s)://` API base URL into the matching `ws(s)://` URL
 * for the voice session endpoint. */
export function toVoiceSessionUrl(baseUrl: string): string {
  const wsBase = baseUrl.replace(/^http/, "ws");
  return `${wsBase}${VOICE_SESSION_PATH}`;
}

export interface VoiceSessionHandlers {
  onEvent(event: VoiceServerEvent): void;
  onOpen?(): void;
  onClose?(): void;
  /** Called for a connection-level error, a non-JSON text frame, or a
   * JSON frame that doesn't match any known shape (ADR-020 Decision 3) —
   * never thrown past this boundary. */
  onError?(error: Error): void;
}

/**
 * Real WebSocket client for the ADR-020 inbound voice session
 * (`wss://.../voice/session`). Sends binary PCM16 16kHz frames produced by
 * `lib/mic-capture.ts`, and dispatches every typed server frame from the
 * frozen wire contract to `handlers.onEvent`.
 *
 * Built on an injectable `WebSocketFactory`, so this class's parsing and
 * dispatch logic is fully unit-testable against a fake socket with no
 * real network connection — the same pattern `lib/graph-stream.ts` uses
 * for its `EventSource`-based SSE client.
 */
export class VoiceSessionClient {
  private socket: WebSocketLike | null = null;

  constructor(
    private readonly baseUrl: string,
    private readonly handlers: VoiceSessionHandlers,
    private readonly createWebSocket: WebSocketFactory = defaultWebSocketFactory,
  ) {}

  connect(): void {
    const socket = this.createWebSocket(toVoiceSessionUrl(this.baseUrl));
    this.socket = socket;

    socket.addEventListener("open", () => this.handlers.onOpen?.());

    socket.addEventListener("message", (event: MessageEvent) => {
      if (typeof event.data !== "string") {
        // The server only ever sends JSON text frames (ADR-020 Decision 3);
        // a binary frame here would be a protocol violation, reported
        // rather than silently dropped.
        this.handlers.onError?.(new Error("received a non-text frame from the voice session"));
        return;
      }

      let raw: unknown;
      try {
        raw = JSON.parse(event.data);
      } catch (err) {
        this.handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
        return;
      }

      const parsed = parseVoiceServerEvent(raw);
      if (parsed === null) {
        this.handlers.onError?.(new Error(`unrecognised voice session frame: ${event.data}`));
        return;
      }

      this.handlers.onEvent(parsed);
    });

    socket.addEventListener("close", () => this.handlers.onClose?.());
    socket.addEventListener("error", () => this.handlers.onError?.(new Error("voice session connection error")));
  }

  /**
   * Sends one binary PCM16 frame. A no-op (never a throw) when the socket
   * isn't open — mic frames arrive continuously on a timer, and a frame
   * produced a tick after `close()` was called is expected during
   * teardown, not a bug to surface.
   */
  sendAudioFrame(frame: ArrayBuffer): void {
    if (this.socket && this.socket.readyState === WEBSOCKET_OPEN_STATE) {
      this.socket.send(frame);
    }
  }

  close(): void {
    this.socket?.close();
    this.socket = null;
  }
}
