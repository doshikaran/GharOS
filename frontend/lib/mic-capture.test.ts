import { describe, expect, it, vi } from "vitest";
import {
  MicCapture,
  type AudioContextLike,
  type AudioNodeLike,
  type ScriptProcessorLike,
} from "./mic-capture";

/** A fake `MediaStream` with just enough surface for `MicCapture.stop()`. */
function fakeMediaStream(): MediaStream {
  const track = { stop: vi.fn() };
  return { getTracks: () => [track] } as unknown as MediaStream;
}

function fakeAudioNode(): AudioNodeLike & { connect: ReturnType<typeof vi.fn<(destination: unknown) => void>>; disconnect: ReturnType<typeof vi.fn<() => void>> } {
  return { connect: vi.fn<(destination: unknown) => void>(), disconnect: vi.fn<() => void>() };
}

function fakeProcessor(): ScriptProcessorLike & { connect: ReturnType<typeof vi.fn<(destination: unknown) => void>>; disconnect: ReturnType<typeof vi.fn<() => void>> } {
  return { onaudioprocess: null, connect: vi.fn<(destination: unknown) => void>(), disconnect: vi.fn<() => void>() };
}

function fakeAudioContext(sampleRate: number, processor: ScriptProcessorLike, source: AudioNodeLike): AudioContextLike {
  return {
    sampleRate,
    destination: {},
    createMediaStreamSource: vi.fn().mockReturnValue(source),
    createScriptProcessor: vi.fn().mockReturnValue(processor),
    close: vi.fn().mockResolvedValue(undefined),
  };
}

describe("MicCapture", () => {
  it("requests mic permission and reports granted, then wires source -> processor -> destination", async () => {
    const stream = fakeMediaStream();
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    const processor = fakeProcessor();
    const source = fakeAudioNode();
    const audioContext = fakeAudioContext(48_000, processor, source);
    const createAudioContext = vi.fn().mockReturnValue(audioContext);

    const onPermissionChange = vi.fn();
    const capture = new MicCapture({ onFrame: vi.fn(), onPermissionChange }, getUserMedia, createAudioContext);

    await capture.start();

    expect(onPermissionChange.mock.calls.map((call) => call[0])).toEqual(["requesting", "granted"]);
    expect(source.connect).toHaveBeenCalledWith(processor);
    expect(processor.connect).toHaveBeenCalledWith(audioContext.destination);
  });

  it("encodes each onaudioprocess tick into a PCM16 frame and forwards it via onFrame", async () => {
    const getUserMedia = vi.fn().mockResolvedValue(fakeMediaStream());
    const processor = fakeProcessor();
    const audioContext = fakeAudioContext(16_000, processor, fakeAudioNode());
    const onFrame = vi.fn();

    const capture = new MicCapture({ onFrame }, getUserMedia, () => audioContext);
    await capture.start();

    expect(processor.onaudioprocess).not.toBeNull();
    const samples = new Float32Array([1, -1, 0]);
    processor.onaudioprocess!({ inputBuffer: { getChannelData: () => samples } });

    expect(onFrame).toHaveBeenCalledOnce();
    const frame = onFrame.mock.calls[0][0] as ArrayBuffer;
    expect(new Int16Array(frame)).toEqual(new Int16Array([0x7fff, -0x8000, 0]));
  });

  it("reports denial distinctly from a generic acquisition error", async () => {
    const deniedError = new DOMException("denied", "NotAllowedError");
    const getUserMedia = vi.fn().mockRejectedValue(deniedError);
    const onPermissionChange = vi.fn();
    const onError = vi.fn();

    const capture = new MicCapture({ onFrame: vi.fn(), onPermissionChange, onError }, getUserMedia);
    await capture.start();

    expect(onPermissionChange).toHaveBeenLastCalledWith("denied");
    expect(onError).toHaveBeenCalledOnce();
  });

  it("reports a non-permission acquisition failure as a generic error state", async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new Error("no device"));
    const onPermissionChange = vi.fn();

    const capture = new MicCapture({ onFrame: vi.fn(), onPermissionChange }, getUserMedia);
    await capture.start();

    expect(onPermissionChange).toHaveBeenLastCalledWith("error");
  });

  it("stop() tears down the processor, source, tracks, and audio context", async () => {
    const track = { stop: vi.fn() };
    const stream = { getTracks: () => [track] } as unknown as MediaStream;
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    const processor = fakeProcessor();
    const source = fakeAudioNode();
    const audioContext = fakeAudioContext(16_000, processor, source);

    const capture = new MicCapture({ onFrame: vi.fn() }, getUserMedia, () => audioContext);
    await capture.start();
    capture.stop();

    expect(processor.disconnect).toHaveBeenCalledOnce();
    expect(source.disconnect).toHaveBeenCalledOnce();
    expect(track.stop).toHaveBeenCalledOnce();
    expect(audioContext.close).toHaveBeenCalledOnce();
  });

  it("stop() before start() never throws", () => {
    const capture = new MicCapture({ onFrame: vi.fn() });
    expect(() => capture.stop()).not.toThrow();
  });
});
