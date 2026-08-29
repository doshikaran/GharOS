import { describe, expect, it } from "vitest";
import { languageDisplayLabel, parseVoiceServerEvent } from "./voice-types";

describe("parseVoiceServerEvent", () => {
  it("parses a session_state frame", () => {
    expect(parseVoiceServerEvent({ type: "session_state", state: "listening" })).toEqual({
      type: "session_state",
      state: "listening",
    });
  });

  it("rejects an unrecognised session state", () => {
    expect(parseVoiceServerEvent({ type: "session_state", state: "dreaming" })).toBeNull();
  });

  it("parses a transcript_partial frame with per-span language tags, mapping snake_case turn_id", () => {
    const raw = {
      type: "transcript_partial",
      spans: [
        { text: "Aarav ko Friday ko", language: "hi", confidence: 0.91 },
        { text: "field trip hai", language: "en", confidence: 0.87 },
      ],
      turn_id: "turn-1",
    };
    expect(parseVoiceServerEvent(raw)).toEqual({
      type: "transcript_partial",
      spans: raw.spans,
      turnId: "turn-1",
    });
  });

  it("parses a transcript_final frame the same way as partial", () => {
    const raw = {
      type: "transcript_final",
      spans: [{ text: "hola", language: "es", confidence: 0.99 }],
      turn_id: "turn-2",
    };
    const parsed = parseVoiceServerEvent(raw);
    expect(parsed?.type).toBe("transcript_final");
  });

  it("rejects a transcript frame with a malformed span", () => {
    const raw = { type: "transcript_final", spans: [{ text: "x" }], turn_id: "turn-3" };
    expect(parseVoiceServerEvent(raw)).toBeNull();
  });

  it("parses a confirmation_prompt frame and requires requires_affirmative === true", () => {
    const raw = { type: "confirmation_prompt", text: "Confirm ₹3,500 to Om Electricals?", requires_affirmative: true, turn_id: "turn-4" };
    expect(parseVoiceServerEvent(raw)).toEqual({
      type: "confirmation_prompt",
      text: raw.text,
      requiresAffirmative: true,
      turnId: "turn-4",
    });
  });

  it("rejects a confirmation_prompt frame missing requires_affirmative", () => {
    const raw = { type: "confirmation_prompt", text: "Confirm?", turn_id: "turn-5" };
    expect(parseVoiceServerEvent(raw)).toBeNull();
  });

  it("parses a response_audio frame", () => {
    const raw = {
      type: "response_audio",
      audio_b64: "QUJD",
      mime_type: "audio/mpeg",
      text: "Theek hai, permission slip sign karke bhej diya.",
      language: "hi",
      turn_id: "turn-6",
    };
    expect(parseVoiceServerEvent(raw)).toEqual({
      type: "response_audio",
      audioB64: "QUJD",
      mimeType: "audio/mpeg",
      text: raw.text,
      language: "hi",
      turnId: "turn-6",
    });
  });

  it("parses an error frame", () => {
    expect(parseVoiceServerEvent({ type: "error", code: "asr_unavailable", message: "ASR backend unreachable" })).toEqual({
      type: "error",
      code: "asr_unavailable",
      message: "ASR backend unreachable",
    });
  });

  it("returns null for a completely unknown frame type", () => {
    expect(parseVoiceServerEvent({ type: "unknown_frame" })).toBeNull();
  });

  it("returns null for non-object input", () => {
    expect(parseVoiceServerEvent("not an object")).toBeNull();
    expect(parseVoiceServerEvent(null)).toBeNull();
    expect(parseVoiceServerEvent(42)).toBeNull();
  });
});

describe("languageDisplayLabel", () => {
  it("maps known codes to their display names", () => {
    expect(languageDisplayLabel("hi")).toBe("Hindi");
    expect(languageDisplayLabel("EN")).toBe("English");
    expect(languageDisplayLabel("mr")).toBe("Marathi");
    expect(languageDisplayLabel("es")).toBe("Spanish");
  });

  it("falls back to the uppercased raw code for an unrecognised language", () => {
    expect(languageDisplayLabel("fr")).toBe("FR");
  });
});
