/**
 * Pure PCM16 mono 16kHz audio-encoding helpers for the live voice session
 * mic pipeline (`docs/adr/020-voice-multilingual-scope.md` Decision 3 —
 * "Client sends binary WebSocket frames, PCM16 mono 16kHz chunks").
 *
 * Kept pure and free of any browser/DOM dependency deliberately, so these
 * functions are unit-testable with plain arrays and no real
 * `AudioContext` or microphone — `lib/mic-capture.ts` is the thin,
 * browser-only wrapper that calls these against real captured samples.
 */

/** The wire contract's fixed target sample rate — never a magic number at
 * call sites. */
export const TARGET_SAMPLE_RATE_HZ = 16_000;

const INT16_MAX = 0x7fff;
const INT16_MIN_MAGNITUDE = 0x8000;

/**
 * Converts 32-bit float PCM samples in [-1, 1] (the Web Audio API's native
 * format) to 16-bit signed integer PCM, clamping out-of-range input rather
 * than wrapping it.
 */
export function floatTo16BitPCM(input: Float32Array): Int16Array {
  const output = new Int16Array(input.length);
  for (let i = 0; i < input.length; i++) {
    const clamped = Math.max(-1, Math.min(1, input[i]));
    output[i] = clamped < 0 ? clamped * INT16_MIN_MAGNITUDE : clamped * INT16_MAX;
  }
  return output;
}

/** Copies an `Int16Array`'s backing bytes into a standalone `ArrayBuffer`
 * sized exactly to the data (never the view's possibly-larger underlying
 * buffer), ready to hand to `WebSocket.send`. */
export function int16ToArrayBuffer(input: Int16Array): ArrayBuffer {
  // `TypedArray.prototype.buffer` is typed `ArrayBufferLike` (it could in
  // principle be a `SharedArrayBuffer`) — every `Int16Array` this module
  // ever constructs comes from `floatTo16BitPCM`'s own `new
  // Int16Array(length)`, never a shared buffer, so this narrowing is safe.
  return input.buffer.slice(input.byteOffset, input.byteOffset + input.byteLength) as ArrayBuffer;
}

/**
 * Downsamples `input` from `inputSampleRate` to `TARGET_SAMPLE_RATE_HZ` by
 * averaging each output sample over its corresponding input window — a
 * simple box-filter decimation, adequate for 16kHz speech-recognition
 * input (this is not a high-fidelity audio product). Returns `input`
 * unchanged when it is already at the target rate.
 *
 * @throws {RangeError} if `inputSampleRate` is below the target rate —
 *   upsampling would fabricate samples that were never captured, which
 *   this function refuses to do silently.
 */
export function downsampleTo16k(input: Float32Array, inputSampleRate: number): Float32Array {
  if (inputSampleRate === TARGET_SAMPLE_RATE_HZ) return input;
  if (inputSampleRate < TARGET_SAMPLE_RATE_HZ) {
    throw new RangeError(
      `mic input sample rate ${inputSampleRate}Hz is below the ${TARGET_SAMPLE_RATE_HZ}Hz wire target, cannot upsample`,
    );
  }

  const ratio = inputSampleRate / TARGET_SAMPLE_RATE_HZ;
  const outputLength = Math.floor(input.length / ratio);
  const output = new Float32Array(outputLength);

  for (let i = 0; i < outputLength; i++) {
    const windowStart = Math.floor(i * ratio);
    const windowEnd = Math.floor((i + 1) * ratio);
    let sum = 0;
    let count = 0;
    for (let j = windowStart; j < windowEnd && j < input.length; j++) {
      sum += input[j];
      count++;
    }
    output[i] = count > 0 ? sum / count : 0;
  }

  return output;
}

/**
 * Encodes one captured audio chunk into a wire-ready PCM16 16kHz
 * `ArrayBuffer` — the single function `lib/mic-capture.ts` calls per
 * `onaudioprocess` tick.
 */
export function encodePcm16Frame(input: Float32Array, inputSampleRate: number): ArrayBuffer {
  const resampled = downsampleTo16k(input, inputSampleRate);
  return int16ToArrayBuffer(floatTo16BitPCM(resampled));
}
