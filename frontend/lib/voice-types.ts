/**
 * TypeScript mirror of the Phase 13 inbound-voice WebSocket wire contract
 * frozen in `docs/adr/020-voice-multilingual-scope.md` Decision 3, and of
 * `contracts.graph_types.LanguageProfile` / `LiteracyMode` (spec §14.3).
 *
 * Source of truth, read directly rather than guessed at:
 *   - ADR-020 Decision 3 — the exact JSON text-frame shapes a `wss://.../
 *     voice/session` server sends (`session_state`, `transcript_partial`,
 *     `transcript_final`, `confirmation_prompt`, `response_audio`,
 *     `error`). Client→server frames are binary PCM16 mono 16kHz audio,
 *     handled by `lib/mic-capture.ts` and `lib/pcm-audio.ts`, not JSON —
 *     there is no client-side JSON frame type to mirror here.
 *   - `contracts/graph_types.py`'s `LanguageProfile`
 *     (`primary_language`, `languages_understood`, `script_preference`,
 *     `code_mixing_profile`, `formality_preference`, `literacy_mode`) and
 *     `LiteracyMode` (`voice_only` | `text_capable` | `both`).
 *
 * **Honest limitation carried into this file's own doc comments, not
 * silently presented as more precise than it is** (ADR-020 Decision 1):
 * `TranscriptSpan.confidence` is a *model-self-reported* confidence, not
 * true acoustic per-token confidence — Vertex AI's `generateContent` audio
 * path does not expose the latter. Every UI surface rendering this value
 * must not imply it is acoustic-engine confidence.
 *
 * These contracts are owned exclusively by the CTO (`contracts/`) and, for
 * the WebSocket wire shape specifically, by ADR-020 as a frozen
 * transport-level agreement between E3 (server) and E4 (this file). This
 * file mirrors that shape; it never redefines it.
 */

// ---------------------------------------------------------------------------
// Session state
// ---------------------------------------------------------------------------

export type SessionState = "listening" | "processing" | "speaking" | "closed";

export const SESSION_STATES: readonly SessionState[] = ["listening", "processing", "speaking", "closed"] as const;

// ---------------------------------------------------------------------------
// Per-span transcript (spec §14.4/§14.12 — "per-span, not per-utterance")
// ---------------------------------------------------------------------------

export interface TranscriptSpan {
  readonly text: string;
  /** BCP-47-ish short code as reported by A64 (e.g. "en", "hi", "mr", "es") — not validated against a closed set here, since the model may report a code this client doesn't have a display label for; `languageDisplayLabel` below falls back to the raw code in that case. */
  readonly language: string;
  /** 0.0-1.0, model-self-reported (ADR-020 Decision 1) — see this file's header comment. */
  readonly confidence: number;
}

// ---------------------------------------------------------------------------
// Server → client frames (ADR-020 Decision 3)
// ---------------------------------------------------------------------------

export interface SessionStateEvent {
  readonly type: "session_state";
  readonly state: SessionState;
}

export interface TranscriptPartialEvent {
  readonly type: "transcript_partial";
  readonly spans: readonly TranscriptSpan[];
  readonly turnId: string;
}

export interface TranscriptFinalEvent {
  readonly type: "transcript_final";
  readonly spans: readonly TranscriptSpan[];
  readonly turnId: string;
}

export interface ConfirmationPromptEvent {
  readonly type: "confirmation_prompt";
  readonly text: string;
  readonly requiresAffirmative: true;
  readonly turnId: string;
}

export interface ResponseAudioEvent {
  readonly type: "response_audio";
  readonly audioB64: string;
  readonly mimeType: string;
  readonly text: string;
  readonly language: string;
  readonly turnId: string;
}

export interface VoiceErrorEvent {
  readonly type: "error";
  readonly code: string;
  readonly message: string;
}

export type VoiceServerEvent =
  | SessionStateEvent
  | TranscriptPartialEvent
  | TranscriptFinalEvent
  | ConfirmationPromptEvent
  | ResponseAudioEvent
  | VoiceErrorEvent;

// ---------------------------------------------------------------------------
// Parsing — every frame arrives as untyped JSON off the wire; this is the
// one place `unknown` gets narrowed into `VoiceServerEvent`, returning
// `null` (never throwing) on anything malformed so a single bad frame
// degrades to a reported error, never a crashed session
// (gharos-standards: a failed parse is a typed failure, not a swallowed
// exception or a fabricated success).
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function isSessionState(value: unknown): value is SessionState {
  return typeof value === "string" && (SESSION_STATES as readonly string[]).includes(value);
}

function parseSpans(value: unknown): readonly TranscriptSpan[] | null {
  if (!Array.isArray(value)) return null;
  const spans: TranscriptSpan[] = [];
  for (const item of value) {
    if (!isRecord(item)) return null;
    const { text, language, confidence } = item;
    if (typeof text !== "string" || typeof language !== "string" || typeof confidence !== "number") {
      return null;
    }
    spans.push({ text, language, confidence });
  }
  return spans;
}

/**
 * Narrows a raw, already-`JSON.parse`d server frame into a typed
 * `VoiceServerEvent`, or `null` if it does not match any known frame shape
 * from ADR-020 Decision 3. Field names on the wire are `snake_case`
 * (`turn_id`, `requires_affirmative`, `audio_b64`, `mime_type`); this
 * function is the single translation point into this codebase's
 * `camelCase` convention.
 */
export function parseVoiceServerEvent(raw: unknown): VoiceServerEvent | null {
  if (!isRecord(raw) || typeof raw.type !== "string") return null;

  switch (raw.type) {
    case "session_state": {
      if (!isSessionState(raw.state)) return null;
      return { type: "session_state", state: raw.state };
    }
    case "transcript_partial":
    case "transcript_final": {
      const spans = parseSpans(raw.spans);
      if (spans === null || typeof raw.turn_id !== "string") return null;
      return { type: raw.type, spans, turnId: raw.turn_id };
    }
    case "confirmation_prompt": {
      if (typeof raw.text !== "string" || typeof raw.turn_id !== "string" || raw.requires_affirmative !== true) {
        return null;
      }
      return { type: "confirmation_prompt", text: raw.text, requiresAffirmative: true, turnId: raw.turn_id };
    }
    case "response_audio": {
      if (
        typeof raw.audio_b64 !== "string" ||
        typeof raw.mime_type !== "string" ||
        typeof raw.text !== "string" ||
        typeof raw.language !== "string" ||
        typeof raw.turn_id !== "string"
      ) {
        return null;
      }
      return {
        type: "response_audio",
        audioB64: raw.audio_b64,
        mimeType: raw.mime_type,
        text: raw.text,
        language: raw.language,
        turnId: raw.turn_id,
      };
    }
    case "error": {
      if (typeof raw.code !== "string" || typeof raw.message !== "string") return null;
      return { type: "error", code: raw.code, message: raw.message };
    }
    default:
      return null;
  }
}

// ---------------------------------------------------------------------------
// Display labels for known language codes — cosmetic only, never used to
// gate behaviour (an unrecognised code still renders, via fallback).
// ---------------------------------------------------------------------------

const LANGUAGE_DISPLAY_LABEL: Readonly<Record<string, string>> = {
  en: "English",
  hi: "Hindi",
  mr: "Marathi",
  es: "Spanish",
};

export function languageDisplayLabel(code: string): string {
  return LANGUAGE_DISPLAY_LABEL[code.toLowerCase()] ?? code.toUpperCase();
}

// ---------------------------------------------------------------------------
// LanguageProfile (contracts/graph_types.py) — spec §14.3, field-for-field
// ---------------------------------------------------------------------------

export type LiteracyMode = "voice_only" | "text_capable" | "both";

export const LITERACY_MODES: readonly LiteracyMode[] = ["voice_only", "text_capable", "both"] as const;

export interface LanguageProfile {
  readonly primaryLanguage: string;
  readonly languagesUnderstood: readonly string[];
  readonly scriptPreference: string;
  /** Learned from observed usage, never user-declared (spec §14.3) — every
   * settings UI must render this read-only. */
  readonly codeMixingProfile: string | null;
  readonly formalityPreference: string | null;
  readonly literacyMode: LiteracyMode;
}

export const LITERACY_MODE_LABEL: Readonly<Record<LiteracyMode, string>> = {
  voice_only: "Voice-only",
  text_capable: "Text-capable",
  both: "Both",
};

export const LITERACY_MODE_DESCRIPTION: Readonly<Record<LiteracyMode, string>> = {
  voice_only: "Never expected to read a visual surface — every confirmation and response for this person must be spoken.",
  text_capable: "Comfortable reading the visual surface; voice is a convenience, not a requirement.",
  both: "Uses voice and the visual surface interchangeably.",
};
