import { act } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { VoiceSessionPanel, type MicCaptureLike, type VoiceSessionClientLike } from "./VoiceSessionPanel";
import type { MicCaptureHandlers } from "@/lib/mic-capture";
import type { VoiceSessionHandlers } from "@/lib/voice-session";
import type { VoiceServerEvent } from "@/lib/voice-types";

class FakeSessionClient implements VoiceSessionClientLike {
  sent: ArrayBuffer[] = [];
  closed = false;
  constructor(
    readonly baseUrl: string,
    readonly handlers: VoiceSessionHandlers,
  ) {}
  connect(): void {}
  close(): void {
    this.closed = true;
  }
  sendAudioFrame(frame: ArrayBuffer): void {
    this.sent.push(frame);
  }
  dispatch(event: VoiceServerEvent): void {
    act(() => this.handlers.onEvent(event));
  }
}

class FakeMicCapture implements MicCaptureLike {
  started = false;
  stopped = false;
  constructor(readonly handlers: MicCaptureHandlers) {}
  async start(): Promise<void> {
    this.started = true;
    this.handlers.onPermissionChange?.("granted");
  }
  stop(): void {
    this.stopped = true;
  }
  emitFrame(frame: ArrayBuffer): void {
    this.handlers.onFrame(frame);
  }
}

function renderPanel() {
  let client: FakeSessionClient | null = null;
  const mics: FakeMicCapture[] = [];

  render(
    <VoiceSessionPanel
      baseUrl="http://api.example"
      createSessionClient={(baseUrl, handlers) => {
        client = new FakeSessionClient(baseUrl, handlers);
        return client;
      }}
      createMicCapture={(handlers) => {
        const mic = new FakeMicCapture(handlers);
        mics.push(mic);
        return mic;
      }}
    />,
  );

  return { getClient: () => client as unknown as FakeSessionClient, mics };
}

beforeEach(() => {
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
  window.HTMLMediaElement.prototype.pause = vi.fn();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VoiceSessionPanel", () => {
  it("connects to the voice session via the injected factory on mount", () => {
    const { getClient } = renderPanel();
    expect(getClient().baseUrl).toBe("http://api.example");
  });

  it("reflects real session_state frames in the session state indicator", () => {
    const { getClient } = renderPanel();
    getClient().dispatch({ type: "session_state", state: "processing" });
    expect(screen.getByText("Thinking")).toBeInTheDocument();
  });

  it("renders a per-span transcript from transcript_partial then replaces it on transcript_final", () => {
    const { getClient } = renderPanel();
    getClient().dispatch({
      type: "transcript_partial",
      turnId: "t1",
      spans: [{ text: "Society maintenance", language: "en", confidence: 0.7 }],
    });
    expect(screen.getByText("Society maintenance")).toBeInTheDocument();
    expect(screen.getByLabelText("still listening")).toBeInTheDocument();

    getClient().dispatch({
      type: "transcript_final",
      turnId: "t1",
      spans: [{ text: "Society maintenance cha payment kela ka", language: "mr", confidence: 0.85 }],
    });
    expect(screen.getByText("Society maintenance cha payment kela ka")).toBeInTheDocument();
    expect(screen.queryByLabelText("still listening")).not.toBeInTheDocument();
  });

  it("renders a confirmation prompt from a confirmation_prompt frame", () => {
    const { getClient } = renderPanel();
    getClient().dispatch({
      type: "confirmation_prompt",
      text: "Pay ₹3,500 to Om Electricals — confirm?",
      requiresAffirmative: true,
      turnId: "t2",
    });
    expect(screen.getByText(/Pay ₹3,500 to Om Electricals/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /confirm it in your Approvals tab/ })).toBeInTheDocument();
  });

  it("renders the spoken response text and audio from a response_audio frame", () => {
    const { getClient } = renderPanel();
    getClient().dispatch({
      type: "response_audio",
      audioB64: "QUJD",
      mimeType: "audio/mpeg",
      text: "Theek hai, sign karke bhej diya.",
      language: "hi",
      turnId: "t3",
    });
    expect(screen.getByText("Theek hai, sign karke bhej diya.")).toBeInTheDocument();
  });

  it("clears a confirmation prompt once a different turn's response arrives", () => {
    const { getClient } = renderPanel();
    getClient().dispatch({ type: "confirmation_prompt", text: "Confirm?", requiresAffirmative: true, turnId: "t4" });
    expect(screen.getByText("Confirm?")).toBeInTheDocument();

    getClient().dispatch({
      type: "response_audio",
      audioB64: "QUJD",
      mimeType: "audio/mpeg",
      text: "Next turn's response.",
      language: "en",
      turnId: "t5",
    });
    expect(screen.queryByText("Confirm?")).not.toBeInTheDocument();
  });

  it("forwards captured mic frames to the session client", async () => {
    const { getClient, mics } = renderPanel();
    fireEvent.mouseDown(screen.getByRole("button", { name: /Hold to talk/ }));
    await act(async () => {});
    const frame = new ArrayBuffer(4);
    mics[0].emitFrame(frame);
    expect(getClient().sent).toEqual([frame]);
  });

  it("barge-in: starting to listen while the server says speaking pauses playback and shows the interruption", async () => {
    const { getClient } = renderPanel();
    getClient().dispatch({
      type: "response_audio",
      audioB64: "QUJD",
      mimeType: "audio/mpeg",
      text: "A long response the household member wants to interrupt.",
      language: "en",
      turnId: "t6",
    });
    getClient().dispatch({ type: "session_state", state: "speaking" });

    fireEvent.mouseDown(screen.getByRole("button", { name: /Hold to talk/ }));
    await act(async () => {});

    expect(window.HTMLMediaElement.prototype.pause).toHaveBeenCalled();
    expect(screen.getByTestId("barge-in-indicator")).toBeInTheDocument();
  });

  it("stops the mic and closes the session on unmount", async () => {
    let client: FakeSessionClient | null = null;
    let mic: FakeMicCapture | null = null;
    const { unmount } = render(
      <VoiceSessionPanel
        baseUrl="http://api.example"
        createSessionClient={(baseUrl, handlers) => {
          client = new FakeSessionClient(baseUrl, handlers);
          return client;
        }}
        createMicCapture={(handlers) => {
          mic = new FakeMicCapture(handlers);
          return mic;
        }}
      />,
    );
    fireEvent.mouseDown(screen.getByRole("button", { name: /Hold to talk/ }));
    await act(async () => {});
    unmount();
    expect(client!.closed).toBe(true);
    expect(mic!.stopped).toBe(true);
  });
});
