"use client";

import { encodePcm16Frame } from "./pcm-audio";

export type MicPermissionState = "idle" | "requesting" | "granted" | "denied" | "error";

export interface MicCaptureHandlers {
  /** Called with one wire-ready PCM16 16kHz frame per audio-processing tick. */
  onFrame(frame: ArrayBuffer): void;
  onPermissionChange?(state: MicPermissionState): void;
  onError?(error: Error): void;
}

/**
 * Minimal shape of `navigator.mediaDevices.getUserMedia`, small enough for
 * a test fake — same injectable-factory discipline as
 * `lib/graph-stream.ts`'s `EventSourceFactory`.
 */
export type GetUserMediaLike = (constraints: MediaStreamConstraints) => Promise<MediaStream>;

/** Minimal shape of the `AudioProcessingEvent` this module reads from. */
export interface AudioProcessingEventLike {
  readonly inputBuffer: { getChannelData(channel: number): Float32Array };
}

/** Minimal shape of a connectable Web Audio node. */
export interface AudioNodeLike {
  connect(destination: unknown): void;
  disconnect(): void;
}

export interface ScriptProcessorLike extends AudioNodeLike {
  onaudioprocess: ((event: AudioProcessingEventLike) => void) | null;
}

export interface AudioContextLike {
  readonly sampleRate: number;
  readonly destination: unknown;
  createMediaStreamSource(stream: MediaStream): AudioNodeLike;
  createScriptProcessor(bufferSize: number, inputChannels: number, outputChannels: number): ScriptProcessorLike;
  close(): Promise<void>;
}

export type AudioContextFactory = () => AudioContextLike;

/** `ScriptProcessorNode`'s buffer size — a Web Audio API-mandated power of
 * two; 4096 samples at 48kHz is ~85ms per frame, a reasonable balance
 * between wire chattiness and latency for speech input. */
const SCRIPT_PROCESSOR_BUFFER_SIZE = 4096;
const MONO_CHANNEL_COUNT = 1;

function defaultGetUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia(constraints);
}

function defaultAudioContextFactory(): AudioContextLike {
  return new AudioContext() as unknown as AudioContextLike;
}

/**
 * True for a real mic-permission denial. Checked via a `name` property
 * rather than `error instanceof Error` — a real browser (and jsdom, which
 * mirrors this) throws `DOMException` for `getUserMedia` rejections, and
 * `DOMException` is not guaranteed to be an `instanceof Error` in every
 * environment, so gating on that would silently misclassify a real
 * denial as a generic error.
 */
function isPermissionDenied(error: unknown): boolean {
  if (typeof error !== "object" || error === null || !("name" in error)) return false;
  const name = (error as { name: unknown }).name;
  return name === "NotAllowedError" || name === "PermissionDeniedError";
}

/**
 * Captures real microphone audio and streams PCM16 16kHz frames to
 * `handlers.onFrame`, matching the ADR-020 WebSocket wire contract's
 * binary frame shape exactly — no fake or pre-recorded audio path.
 *
 * Uses a `ScriptProcessorNode` rather than an `AudioWorkletNode` —
 * deprecated but universally supported with zero extra worklet-module
 * file to ship, a deliberate simplicity trade-off for this phase's scope,
 * not an oversight. Every browser dependency (`getUserMedia`,
 * `AudioContext`) is constructor-injectable, so this class's start/stop
 * lifecycle and frame-encoding wiring are unit-testable without a real
 * microphone (same discipline as `lib/graph-stream.ts`'s injectable
 * `EventSource`).
 */
export class MicCapture {
  private stream: MediaStream | null = null;
  private audioContext: AudioContextLike | null = null;
  private processor: ScriptProcessorLike | null = null;
  private source: AudioNodeLike | null = null;

  constructor(
    private readonly handlers: MicCaptureHandlers,
    private readonly getUserMedia: GetUserMediaLike = defaultGetUserMedia,
    private readonly createAudioContext: AudioContextFactory = defaultAudioContextFactory,
  ) {}

  /**
   * Requests mic permission and begins streaming frames. Resolves once
   * capture has started; a permission denial or any other acquisition
   * failure resolves normally too (never rejects) after reporting through
   * `handlers.onPermissionChange`/`handlers.onError` — the caller reads
   * session state from those callbacks, not from a rejected promise.
   */
  async start(): Promise<void> {
    this.handlers.onPermissionChange?.("requesting");

    let stream: MediaStream;
    try {
      stream = await this.getUserMedia({
        audio: { channelCount: MONO_CHANNEL_COUNT, echoCancellation: true, noiseSuppression: true },
      });
    } catch (err) {
      this.handlers.onPermissionChange?.(isPermissionDenied(err) ? "denied" : "error");
      this.handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
      return;
    }

    this.handlers.onPermissionChange?.("granted");
    this.stream = stream;

    const audioContext = this.createAudioContext();
    this.audioContext = audioContext;

    const source = audioContext.createMediaStreamSource(stream);
    this.source = source;

    const processor = audioContext.createScriptProcessor(SCRIPT_PROCESSOR_BUFFER_SIZE, MONO_CHANNEL_COUNT, MONO_CHANNEL_COUNT);
    this.processor = processor;

    processor.onaudioprocess = (event) => {
      const samples = event.inputBuffer.getChannelData(0);
      try {
        this.handlers.onFrame(encodePcm16Frame(samples, audioContext.sampleRate));
      } catch (err) {
        this.handlers.onError?.(err instanceof Error ? err : new Error(String(err)));
      }
    };

    source.connect(processor);
    processor.connect(audioContext.destination);
  }

  /** Tears down the mic stream, processor, and audio context. Safe to call
   * even if `start()` never completed or was never called. */
  stop(): void {
    if (this.processor) {
      this.processor.onaudioprocess = null;
      this.processor.disconnect();
      this.processor = null;
    }
    this.source?.disconnect();
    this.source = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    if (this.audioContext) {
      void this.audioContext.close();
      this.audioContext = null;
    }
  }
}
