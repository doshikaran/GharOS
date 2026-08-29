import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { LanguageProfileSettings } from "./LanguageProfileSettings";
import { VOICE_HOUSEHOLD_PERSONS } from "@/lib/voice-persons";

const DADI_PROFILE = {
  primary_language: "hi",
  languages_understood: ["hi", "mr"],
  script_preference: "devanagari",
  code_mixing_profile: "hinglish-light",
  formality_preference: "formal",
  literacy_mode: "voice_only",
};

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("LanguageProfileSettings", () => {
  it("loads and renders the first household member's profile on mount", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(DADI_PROFILE));
    vi.stubGlobal("fetch", fetchImpl);

    render(<LanguageProfileSettings baseUrl="http://api.example" />);

    await waitFor(() => expect(screen.getByLabelText("Primary language")).toHaveValue("hi"));
    expect(fetchImpl).toHaveBeenCalledWith(
      `http://api.example/voice/persons/${VOICE_HOUSEHOLD_PERSONS[0].personId}/language-profile`,
      { method: "GET" },
    );
  });

  it("renders codeMixingProfile as read-only text, with no input control for it", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(DADI_PROFILE)));
    render(<LanguageProfileSettings baseUrl="http://api.example" />);

    await waitFor(() => expect(screen.getByText("hinglish-light")).toBeInTheDocument());
    // No checkbox/radio/select is wired to code-mixing anywhere in the form.
    expect(screen.queryByLabelText(/code.mixing/i)).not.toBeInTheDocument();
  });

  it("shows an honest failure, naming a likely-undeployed endpoint on a 404, rather than pretending to load", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("not found", { status: 404, statusText: "Not Found" })));
    render(<LanguageProfileSettings baseUrl="http://api.example" />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/endpoint may not be deployed yet/));
  });

  it("re-fetches when the household member selection changes", async () => {
    const fetchImpl = vi.fn().mockResolvedValue(jsonResponse(DADI_PROFILE));
    vi.stubGlobal("fetch", fetchImpl);
    render(<LanguageProfileSettings baseUrl="http://api.example" />);
    await waitFor(() => expect(fetchImpl).toHaveBeenCalledTimes(1));

    const secondPerson = VOICE_HOUSEHOLD_PERSONS[1];
    fireEvent.change(screen.getByLabelText("Household member"), { target: { value: secondPerson.personId } });

    await waitFor(() =>
      expect(fetchImpl).toHaveBeenLastCalledWith(
        `http://api.example/voice/persons/${secondPerson.personId}/language-profile`,
        { method: "GET" },
      ),
    );
  });

  it("saves an edited literacy_mode via PATCH without ever including code_mixing_profile", async () => {
    const fetchImpl = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (init?.method === "PATCH") return Promise.resolve(jsonResponse({ ...DADI_PROFILE, literacy_mode: "text_capable" }));
      return Promise.resolve(jsonResponse(DADI_PROFILE));
    });
    vi.stubGlobal("fetch", fetchImpl);

    render(<LanguageProfileSettings baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByLabelText("Primary language")).toHaveValue("hi"));

    fireEvent.click(screen.getByRole("radio", { name: /Text-capable/ }));
    fireEvent.click(screen.getByRole("button", { name: /Save language profile/ }));

    await waitFor(() => expect(screen.getByText("Saved.")).toBeInTheDocument());

    const patchCall = fetchImpl.mock.calls.find(([, init]) => (init as RequestInit | undefined)?.method === "PATCH");
    expect(patchCall).toBeDefined();
    const body = JSON.parse((patchCall![1] as RequestInit).body as string);
    expect(body.literacy_mode).toBe("text_capable");
    expect(body).not.toHaveProperty("code_mixing_profile");
  });
});
