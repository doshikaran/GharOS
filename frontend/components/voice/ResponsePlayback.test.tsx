import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { ELDER_MODE_PLAYBACK_RATE, ResponsePlayback } from "./ResponsePlayback";

// jsdom does not implement real media playback — stub it so this test
// exercises this component's own logic (which src/playbackRate it sets,
// when it calls play()) without depending on jsdom's unimplemented
// HTMLMediaElement internals.
beforeEach(() => {
  window.HTMLMediaElement.prototype.play = vi.fn().mockResolvedValue(undefined);
});

afterEach(() => {
  vi.restoreAllMocks();
});

const SAMPLE_RESPONSE = {
  type: "response_audio" as const,
  audioB64: "QUJD",
  mimeType: "audio/mpeg",
  text: "Theek hai, permission slip sign karke bhej diya.",
  language: "hi",
  turnId: "turn-1",
};

describe("ResponsePlayback", () => {
  it("shows guidance when there is no response yet", () => {
    render(<ResponsePlayback response={null} elderMode={false} />);
    expect(screen.getByText(/hasn't responded yet/)).toBeInTheDocument();
  });

  it("always renders the response text alongside the audio — never audio-only", () => {
    render(<ResponsePlayback response={SAMPLE_RESPONSE} elderMode={false} />);
    expect(screen.getByText(SAMPLE_RESPONSE.text)).toBeInTheDocument();
    const audio = screen.getByTestId("response-audio") as HTMLAudioElement;
    expect(audio.src).toContain("data:audio/mpeg;base64,QUJD");
  });

  it("plays at normal rate by default and at the elder-mode rate when elderMode is on", () => {
    const { rerender } = render(<ResponsePlayback response={SAMPLE_RESPONSE} elderMode={false} />);
    const audio = screen.getByTestId("response-audio") as HTMLAudioElement;
    expect(audio.playbackRate).toBe(1);

    rerender(<ResponsePlayback response={{ ...SAMPLE_RESPONSE, turnId: "turn-2" }} elderMode={true} />);
    expect(audio.playbackRate).toBe(ELDER_MODE_PLAYBACK_RATE);
  });

  it("the Play again button replays from the start at the current pacing", () => {
    render(<ResponsePlayback response={SAMPLE_RESPONSE} elderMode={true} />);
    const audio = screen.getByTestId("response-audio") as HTMLAudioElement;
    Object.defineProperty(audio, "currentTime", { value: 5, writable: true });

    fireEvent.click(screen.getByRole("button", { name: "Play again" }));

    expect(audio.currentTime).toBe(0);
    expect(audio.playbackRate).toBe(ELDER_MODE_PLAYBACK_RATE);
    expect(window.HTMLMediaElement.prototype.play).toHaveBeenCalled();
  });
});
