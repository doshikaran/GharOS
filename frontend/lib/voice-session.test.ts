import { describe, expect, it, vi } from "vitest";
import { toVoiceSessionUrl, VoiceSessionClient, type WebSocketLike } from "./voice-session";

/** A minimal fake `WebSocketLike` a test can drive by hand — no real
 * network connection involved, same discipline as `graph-stream.test.ts`'s
 * `FakeEventSource`. */
class FakeWebSocket implements WebSocketLike {
  readyState = 0; // CONNECTING
  sent: Array<string | ArrayBufferLike | Blob | ArrayBufferView> = [];
  closed = false;
  listeners = new Map<string, Set<(event: MessageEvent) => void>>();

  addEventListener(type: "open" | "message" | "close" | "error", listener: (event: MessageEvent) => void): void {
    if (!this.listeners.has(type)) this.listeners.set(type, new Set());
    this.listeners.get(type)!.add(listener);
  }

  send(data: string | ArrayBufferLike | Blob | ArrayBufferView): void {
    this.sent.push(data);
  }

  close(): void {
    this.closed = true;
    this.dispatch("close");
  }

  dispatch(type: string, event?: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) listener(event as MessageEvent);
  }

  open(): void {
    this.readyState = 1; // OPEN
    this.dispatch("open");
  }

  message(data: string): void {
    this.dispatch("message", { data });
  }
}

describe("toVoiceSessionUrl", () => {
  it("rewrites http(s) to ws(s) and appends the session path", () => {
    expect(toVoiceSessionUrl("http://localhost:8000")).toBe("ws://localhost:8000/voice/session");
    expect(toVoiceSessionUrl("https://api.example.com")).toBe("wss://api.example.com/voice/session");
  });
});

describe("VoiceSessionClient", () => {
  it("connects via the injected factory to the voice session URL", () => {
    const fake = new FakeWebSocket();
    const factory = vi.fn().mockReturnValue(fake);
    const client = new VoiceSessionClient("http://api.example", { onEvent: () => {} }, factory);
    client.connect();
    expect(factory).toHaveBeenCalledWith("ws://api.example/voice/session");
  });

  it("calls onOpen when the socket opens", () => {
    const fake = new FakeWebSocket();
    const onOpen = vi.fn();
    const client = new VoiceSessionClient("http://api.example", { onEvent: () => {}, onOpen }, () => fake);
    client.connect();
    fake.open();
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it("dispatches a parsed transcript_partial event", () => {
    const fake = new FakeWebSocket();
    const onEvent = vi.fn();
    const client = new VoiceSessionClient("http://api.example", { onEvent }, () => fake);
    client.connect();
    fake.message(
      JSON.stringify({
        type: "transcript_partial",
        spans: [{ text: "Society maintenance", language: "en", confidence: 0.8 }],
        turn_id: "t1",
      }),
    );
    expect(onEvent).toHaveBeenCalledWith({
      type: "transcript_partial",
      spans: [{ text: "Society maintenance", language: "en", confidence: 0.8 }],
      turnId: "t1",
    });
  });

  it("reports malformed JSON as an error, never as a crash or a dropped-silently frame", () => {
    const fake = new FakeWebSocket();
    const onError = vi.fn();
    const onEvent = vi.fn();
    const client = new VoiceSessionClient("http://api.example", { onEvent, onError }, () => fake);
    client.connect();
    fake.message("{not valid json");
    expect(onError).toHaveBeenCalledOnce();
    expect(onEvent).not.toHaveBeenCalled();
  });

  it("reports an unrecognised-but-valid-JSON frame as an error", () => {
    const fake = new FakeWebSocket();
    const onError = vi.fn();
    const client = new VoiceSessionClient("http://api.example", { onEvent: () => {}, onError }, () => fake);
    client.connect();
    fake.message(JSON.stringify({ type: "mystery_frame" }));
    expect(onError).toHaveBeenCalledOnce();
  });

  it("sendAudioFrame only sends while the socket is OPEN", () => {
    const fake = new FakeWebSocket();
    const client = new VoiceSessionClient("http://api.example", { onEvent: () => {} }, () => fake);
    client.connect();
    const frame = new ArrayBuffer(4);

    client.sendAudioFrame(frame); // still CONNECTING, dropped
    expect(fake.sent).toHaveLength(0);

    fake.open();
    client.sendAudioFrame(frame);
    expect(fake.sent).toEqual([frame]);
  });

  it("close() closes the underlying socket and further sendAudioFrame calls are no-ops", () => {
    const fake = new FakeWebSocket();
    const client = new VoiceSessionClient("http://api.example", { onEvent: () => {} }, () => fake);
    client.connect();
    fake.open();
    client.close();
    expect(fake.closed).toBe(true);
    client.sendAudioFrame(new ArrayBuffer(2));
    expect(fake.sent).toHaveLength(0);
  });

  it("calls onClose when the socket closes", () => {
    const fake = new FakeWebSocket();
    const onClose = vi.fn();
    const client = new VoiceSessionClient("http://api.example", { onEvent: () => {}, onClose }, () => fake);
    client.connect();
    fake.open();
    fake.close();
    expect(onClose).toHaveBeenCalledOnce();
  });
});
