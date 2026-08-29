import { describe, expect, it } from "vitest";
import { downsampleTo16k, encodePcm16Frame, floatTo16BitPCM, int16ToArrayBuffer, TARGET_SAMPLE_RATE_HZ } from "./pcm-audio";

describe("floatTo16BitPCM", () => {
  it("converts full-scale positive and negative samples to the correct 16-bit extremes", () => {
    const result = floatTo16BitPCM(new Float32Array([1, -1, 0]));
    expect(result[0]).toBe(0x7fff);
    expect(result[1]).toBe(-0x8000);
    expect(result[2]).toBe(0);
  });

  it("clamps out-of-range input instead of wrapping", () => {
    const result = floatTo16BitPCM(new Float32Array([2.5, -3.1]));
    expect(result[0]).toBe(0x7fff);
    expect(result[1]).toBe(-0x8000);
  });
});

describe("int16ToArrayBuffer", () => {
  it("produces a buffer sized exactly to the data, not the view's underlying buffer", () => {
    const backing = new ArrayBuffer(16);
    const view = new Int16Array(backing, 4, 3); // 3 samples, offset 4 bytes, into a 16-byte buffer
    view.set([1, 2, 3]);
    const result = int16ToArrayBuffer(view);
    expect(result.byteLength).toBe(6);
    expect(Array.from(new Int16Array(result))).toEqual([1, 2, 3]);
  });
});

describe("downsampleTo16k", () => {
  it("returns the input unchanged when already at the target rate", () => {
    const input = new Float32Array([0.1, 0.2, 0.3]);
    expect(downsampleTo16k(input, TARGET_SAMPLE_RATE_HZ)).toBe(input);
  });

  it("halves sample count when input is at double the target rate", () => {
    const input = new Float32Array([0, 1, 0, 1, 0, 1, 0, 1]);
    const result = downsampleTo16k(input, TARGET_SAMPLE_RATE_HZ * 2);
    expect(result.length).toBe(4);
    // Each output sample is the mean of a 2-sample window of alternating 0/1.
    for (const sample of result) {
      expect(sample).toBeCloseTo(0.5, 5);
    }
  });

  it("throws rather than upsampling when input is below the target rate", () => {
    expect(() => downsampleTo16k(new Float32Array([0.1]), TARGET_SAMPLE_RATE_HZ / 2)).toThrow(RangeError);
  });
});

describe("encodePcm16Frame", () => {
  it("downsamples then encodes to PCM16 in one pass", () => {
    const input = new Float32Array([1, 1, -1, -1]); // at 32kHz -> 2 samples at 16kHz
    const buffer = encodePcm16Frame(input, TARGET_SAMPLE_RATE_HZ * 2);
    const view = new Int16Array(buffer);
    expect(view.length).toBe(2);
    expect(view[0]).toBe(0x7fff);
    expect(view[1]).toBe(-0x8000);
  });
});
