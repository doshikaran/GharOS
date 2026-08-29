import { describe, expect, it, vi } from "vitest";
import {
  enrollmentPath,
  enrollVoiceprint,
  fetchLanguageProfile,
  languageProfilePath,
  updateLanguageProfile,
  type LanguageProfilePatch,
} from "./language-profile";

const WIRE_PROFILE = {
  primary_language: "hi",
  languages_understood: ["hi", "en"],
  script_preference: "devanagari",
  code_mixing_profile: "hinglish-heavy",
  formality_preference: "informal",
  literacy_mode: "voice_only",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

describe("path builders", () => {
  it("URL-encodes the person id", () => {
    expect(languageProfilePath("person/weird id")).toBe("/voice/persons/person%2Fweird%20id/language-profile");
    expect(enrollmentPath("person-maya")).toBe("/voice/persons/person-maya/enroll");
  });
});

describe("fetchLanguageProfile", () => {
  it("GETs the language-profile path and maps snake_case wire fields to camelCase", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(WIRE_PROFILE));
    const outcome = await fetchLanguageProfile("http://api.example", "person-dadi", fetchImpl);

    expect(fetchImpl).toHaveBeenCalledWith("http://api.example/voice/persons/person-dadi/language-profile", { method: "GET" });
    expect(outcome).toEqual({
      status: "success",
      profile: {
        primaryLanguage: "hi",
        languagesUnderstood: ["hi", "en"],
        scriptPreference: "devanagari",
        codeMixingProfile: "hinglish-heavy",
        formalityPreference: "informal",
        literacyMode: "voice_only",
      },
    });
  });

  it("reports a network failure distinctly", async () => {
    const fetchImpl = vi.fn().mockRejectedValue(new TypeError("Failed to fetch"));
    const outcome = await fetchLanguageProfile("http://api.example", "person-dadi", fetchImpl);
    expect(outcome).toEqual({ status: "failure", kind: "network", message: "Failed to fetch" });
  });

  it("reports a non-2xx response as an http-error, e.g. the endpoint not existing yet", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response("not found", { status: 404, statusText: "Not Found" }));
    const outcome = await fetchLanguageProfile("http://api.example", "person-dadi", fetchImpl);
    expect(outcome).toEqual({ status: "failure", kind: "http-error", message: "HTTP 404 Not Found", httpStatus: 404 });
  });

  it("reports a 2xx response with a body that doesn't match the shape as invalid-json", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ unexpected: true }));
    const outcome = await fetchLanguageProfile("http://api.example", "person-dadi", fetchImpl);
    expect(outcome.status).toBe("failure");
    expect((outcome as { kind: string }).kind).toBe("invalid-json");
  });
});

describe("updateLanguageProfile", () => {
  it("PATCHes only the provided fields, translated to snake_case, and never sends code_mixing_profile", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(WIRE_PROFILE));
    await updateLanguageProfile(
      "http://api.example",
      "person-maya",
      { literacyMode: "text_capable", primaryLanguage: "mr" },
      fetchImpl,
    );

    expect(fetchImpl).toHaveBeenCalledOnce();
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.example/voice/persons/person-maya/language-profile");
    expect(init.method).toBe("PATCH");
    const body = JSON.parse(init.body as string);
    expect(body).toEqual({ literacy_mode: "text_capable", primary_language: "mr" });
    expect(body).not.toHaveProperty("code_mixing_profile");
  });

  it("the LanguageProfilePatch type structurally excludes codeMixingProfile", () => {
    // Type-level guard: this line fails to compile (and this test fails,
    // via an unused/unmatched ts-expect-error) if codeMixingProfile ever
    // becomes assignable on a patch (spec §14.3: "learned, not declared").
    const patchWithForbiddenField: LanguageProfilePatch = {
      primaryLanguage: "hi",
      // @ts-expect-error -- codeMixingProfile must never be an editable patch field
      codeMixingProfile: "should-not-compile",
    };
    expect(patchWithForbiddenField.primaryLanguage).toBe("hi");
  });
});

describe("enrollVoiceprint", () => {
  it("POSTs a JSON body of base64-encoded audio + mime type to the real /enroll endpoint", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ person_id: "person-dadi", voiceprint_ref: "vp-abc123", enrolled_at: "2026-08-29T10:00:00Z" }),
    );
    const clip = new Blob(["fake-audio-bytes"], { type: "audio/webm" });
    const outcome = await enrollVoiceprint("http://api.example", "person-dadi", clip, fetchImpl);

    expect(outcome).toEqual({
      status: "success",
      personId: "person-dadi",
      voiceprintRef: "vp-abc123",
      enrolledAt: "2026-08-29T10:00:00Z",
    });

    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.example/voice/persons/person-dadi/enroll");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    const body = JSON.parse(init.body as string) as { audio_b64: string; mime_type: string };
    expect(body.mime_type).toBe("audio/webm");
    expect(body.audio_b64).toBe(btoa("fake-audio-bytes"));
    // Never the old multipart shape.
    expect(init.body).not.toBeInstanceOf(FormData);
  });

  it("falls back to a default mime type when the recorded Blob reports none", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(
      jsonResponse({ person_id: "person-dadi", voiceprint_ref: "vp-xyz", enrolled_at: "2026-08-29T10:00:00Z" }),
    );
    const clip = new Blob(["bytes"]); // no explicit type
    await enrollVoiceprint("http://api.example", "person-dadi", clip, fetchImpl);
    const [, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as { mime_type: string };
    expect(body.mime_type).toBe("audio/webm");
  });

  it("reports a failed enrollment honestly rather than claiming success", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(new Response(null, { status: 501, statusText: "Not Implemented" }));
    const outcome = await enrollVoiceprint("http://api.example", "person-dadi", new Blob(["x"]), fetchImpl);
    expect(outcome).toEqual({ status: "failure", message: "HTTP 501 Not Implemented" });
  });

  it("reports a 2xx response that doesn't match the expected enrollment shape as a failure, not a fabricated success", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse({ unexpected: true }));
    const outcome = await enrollVoiceprint("http://api.example", "person-dadi", new Blob(["x"]), fetchImpl);
    expect(outcome.status).toBe("failure");
  });
});
