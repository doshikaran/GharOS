/**
 * Real fetch client for per-person language-profile read/update and
 * voiceprint enrollment (this phase's charter: "a `PATCH
 * /voice/persons/{person_id}/language-profile` taking
 * `{primary_language, languages_understood, script_preference,
 * code_mixing_profile, formality_preference, literacy_mode}`, matching
 * `contracts.graph_types.LanguageProfile` field-for-field", plus "a
 * voiceprint-enrollment endpoint").
 *
 * **DOCUMENTED INTEGRATION SEAM**, same honesty discipline as
 * `lib/council.ts`'s "no backend endpoint exists yet" seam comment, with
 * one difference: this file is a REAL `fetch` against a real path from
 * day one, never a fixture. `backend/app/voice/` is E3's parallel Phase 13
 * work. Every function here degrades to a typed `"failure"` outcome
 * (network error, HTTP error, or invalid JSON — same three-way split as
 * `lib/status-checks.ts`) rather than crashing or fabricating success.
 *
 * `GET`/`PATCH /voice/persons/{id}/language-profile` were this file's
 * best-faith reading of the charter's frozen field shape and E3 has since
 * independently verified both match the real, deployed endpoint exactly —
 * no changes needed there.
 *
 * The enrollment endpoint did differ from this file's original guess and
 * has been reconciled to E3's real, live-tested shape: `POST
 * /voice/persons/{person_id}/enroll`, a JSON body of
 * `{audio_b64: str, mime_type: str}` (not the multipart form this file
 * originally sent), returning `{person_id, voiceprint_ref, enrolled_at}`.
 * `enrollVoiceprint` base64-encodes the recorded clip client-side
 * (`arrayBufferToBase64`) before sending it.
 */

import type { LanguageProfile, LiteracyMode } from "./voice-types";

export function languageProfilePath(personId: string): string {
  return `/voice/persons/${encodeURIComponent(personId)}/language-profile`;
}

export function enrollmentPath(personId: string): string {
  return `/voice/persons/${encodeURIComponent(personId)}/enroll`;
}

/** Wire shape — field-for-field `contracts.graph_types.LanguageProfile`. */
interface LanguageProfileWire {
  readonly primary_language: string;
  readonly languages_understood: readonly string[];
  readonly script_preference: string;
  readonly code_mixing_profile: string | null;
  readonly formality_preference: string | null;
  readonly literacy_mode: LiteracyMode;
}

function fromWire(wire: LanguageProfileWire): LanguageProfile {
  return {
    primaryLanguage: wire.primary_language,
    languagesUnderstood: wire.languages_understood,
    scriptPreference: wire.script_preference,
    codeMixingProfile: wire.code_mixing_profile,
    formalityPreference: wire.formality_preference,
    literacyMode: wire.literacy_mode,
  };
}

function isLanguageProfileWire(value: unknown): value is LanguageProfileWire {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.primary_language === "string" &&
    Array.isArray(record.languages_understood) &&
    record.languages_understood.every((item) => typeof item === "string") &&
    typeof record.script_preference === "string" &&
    (record.code_mixing_profile === null || typeof record.code_mixing_profile === "string") &&
    (record.formality_preference === null || typeof record.formality_preference === "string") &&
    typeof record.literacy_mode === "string"
  );
}

/**
 * A patch may update anything except `codeMixingProfile` — spec §14.3:
 * "observed mixing pattern; learned, not declared." Enforced at the type
 * level, not just by UI convention, so no caller can accidentally wire an
 * editable control to it.
 */
export type LanguageProfilePatch = Partial<Omit<LanguageProfile, "codeMixingProfile">>;

function toWirePatch(patch: LanguageProfilePatch): Partial<LanguageProfileWire> {
  // `LanguageProfileWire`'s fields are `readonly` (this codebase's
  // frozen-domain-object convention), so this builds a plain mutable
  // record and returns it typed as the readonly shape — building it any
  // other way would fight the type system for no safety benefit, since
  // this function's only caller passes the result straight into
  // `JSON.stringify`.
  const wire: Partial<Record<keyof LanguageProfileWire, unknown>> = {};
  if (patch.primaryLanguage !== undefined) wire.primary_language = patch.primaryLanguage;
  if (patch.languagesUnderstood !== undefined) wire.languages_understood = patch.languagesUnderstood;
  if (patch.scriptPreference !== undefined) wire.script_preference = patch.scriptPreference;
  if (patch.formalityPreference !== undefined) wire.formality_preference = patch.formalityPreference;
  if (patch.literacyMode !== undefined) wire.literacy_mode = patch.literacyMode;
  return wire as Partial<LanguageProfileWire>;
}

export type FetchLike = typeof fetch;

export interface LanguageProfileSuccess {
  readonly status: "success";
  readonly profile: LanguageProfile;
}

export type LanguageProfileFailureKind = "network" | "http-error" | "invalid-json";

export interface LanguageProfileFailure {
  readonly status: "failure";
  readonly kind: LanguageProfileFailureKind;
  readonly message: string;
  readonly httpStatus?: number;
}

export type LanguageProfileOutcome = LanguageProfileSuccess | LanguageProfileFailure;

async function parseProfileResponse(response: Response): Promise<LanguageProfileOutcome> {
  const rawText = await response.text();
  let parsed: unknown = null;
  let parseFailed = false;
  if (rawText.length > 0) {
    try {
      parsed = JSON.parse(rawText);
    } catch {
      parseFailed = true;
    }
  }

  if (!response.ok) {
    return {
      status: "failure",
      kind: "http-error",
      message: `HTTP ${response.status} ${response.statusText}`,
      httpStatus: response.status,
    };
  }

  if (parseFailed || !isLanguageProfileWire(parsed)) {
    return {
      status: "failure",
      kind: "invalid-json",
      message: "Server responded 2xx but the body was not a valid LanguageProfile.",
      httpStatus: response.status,
    };
  }

  return { status: "success", profile: fromWire(parsed) };
}

/** Fetches `personId`'s current language profile. */
export async function fetchLanguageProfile(
  baseUrl: string,
  personId: string,
  fetchImpl: FetchLike = fetch,
): Promise<LanguageProfileOutcome> {
  try {
    const response = await fetchImpl(`${baseUrl}${languageProfilePath(personId)}`, { method: "GET" });
    return await parseProfileResponse(response);
  } catch (err) {
    return { status: "failure", kind: "network", message: err instanceof Error ? err.message : String(err) };
  }
}

/** Patches `personId`'s language profile. `patch` may never include
 * `codeMixingProfile` — see `LanguageProfilePatch`. */
export async function updateLanguageProfile(
  baseUrl: string,
  personId: string,
  patch: LanguageProfilePatch,
  fetchImpl: FetchLike = fetch,
): Promise<LanguageProfileOutcome> {
  try {
    const response = await fetchImpl(`${baseUrl}${languageProfilePath(personId)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(toWirePatch(patch)),
    });
    return await parseProfileResponse(response);
  } catch (err) {
    return { status: "failure", kind: "network", message: err instanceof Error ? err.message : String(err) };
  }
}

export interface VoiceprintEnrollmentSuccess {
  readonly status: "success";
  readonly personId: string;
  readonly voiceprintRef: string;
  readonly enrolledAt: string;
}

export interface VoiceprintEnrollmentFailure {
  readonly status: "failure";
  readonly message: string;
}

export type VoiceprintEnrollmentOutcome = VoiceprintEnrollmentSuccess | VoiceprintEnrollmentFailure;

interface EnrollmentResponseWire {
  readonly person_id: string;
  readonly voiceprint_ref: string;
  readonly enrolled_at: string;
}

function isEnrollmentResponseWire(value: unknown): value is EnrollmentResponseWire {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.person_id === "string" &&
    typeof record.voiceprint_ref === "string" &&
    typeof record.enrolled_at === "string"
  );
}

/**
 * Base64-encodes an `ArrayBuffer` in fixed-size chunks rather than a
 * single `String.fromCharCode(...bytes)` spread — spreading a large
 * typed array as call arguments can overflow the call stack, and a
 * multi-second audio recording is easily large enough to hit that.
 */
function arrayBufferToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  const CHUNK_SIZE = 0x8000;
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += CHUNK_SIZE) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + CHUNK_SIZE));
  }
  return btoa(binary);
}

/** Fallback MIME type when a recorded `Blob` reports none (some
 * `MediaRecorder` implementations leave `Blob.type` empty). */
const DEFAULT_VOICEPRINT_MIME_TYPE = "audio/webm";

/**
 * Uploads a short recorded reference clip (real `MediaRecorder` output,
 * see `components/voice/VoiceprintEnrollment.tsx`) for A66 Speaker
 * Identification to enrol against — a real `POST
 * /voice/persons/{person_id}/enroll` with a JSON body of
 * `{audio_b64, mime_type}`, matching E3's real, live-tested endpoint
 * shape exactly (reconciled from this file's original multipart-form
 * guess).
 */
export async function enrollVoiceprint(
  baseUrl: string,
  personId: string,
  clip: Blob,
  fetchImpl: FetchLike = fetch,
): Promise<VoiceprintEnrollmentOutcome> {
  try {
    const buffer = await clip.arrayBuffer();
    const audioB64 = arrayBufferToBase64(buffer);
    const mimeType = clip.type || DEFAULT_VOICEPRINT_MIME_TYPE;

    const response = await fetchImpl(`${baseUrl}${enrollmentPath(personId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ audio_b64: audioB64, mime_type: mimeType }),
    });

    if (!response.ok) {
      return { status: "failure", message: `HTTP ${response.status} ${response.statusText}` };
    }

    const rawText = await response.text();
    let parsed: unknown = null;
    try {
      parsed = rawText.length > 0 ? JSON.parse(rawText) : null;
    } catch {
      return { status: "failure", message: "Server responded 2xx but the body was not valid JSON." };
    }
    if (!isEnrollmentResponseWire(parsed)) {
      return {
        status: "failure",
        message: "Server responded 2xx but the body didn't match the expected enrollment response shape.",
      };
    }

    return {
      status: "success",
      personId: parsed.person_id,
      voiceprintRef: parsed.voiceprint_ref,
      enrolledAt: parsed.enrolled_at,
    };
  } catch (err) {
    return { status: "failure", message: err instanceof Error ? err.message : String(err) };
  }
}
