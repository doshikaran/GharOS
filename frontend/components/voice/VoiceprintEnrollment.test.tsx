import { act } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { VoiceprintEnrollment, type MediaRecorderLike } from "./VoiceprintEnrollment";

class FakeRecorder implements MediaRecorderLike {
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  started = false;

  start(): void {
    this.started = true;
  }

  stop(): void {
    this.ondataavailable?.({ data: new Blob(["chunk"]) });
    this.onstop?.();
  }
}

function fakeStream(): MediaStream {
  const track = { stop: vi.fn() };
  return { getTracks: () => [track] } as unknown as MediaStream;
}

afterEach(() => {
  vi.restoreAllMocks();
});

describe("VoiceprintEnrollment", () => {
  it("records a short clip and uploads it via a real fetch call", async () => {
    const stream = fakeStream();
    const getUserMedia = vi.fn().mockResolvedValue(stream);
    const recorder = new FakeRecorder();
    const createMediaRecorder = vi.fn().mockReturnValue(recorder);
    const fetchImpl = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({ person_id: "person-dadi", voiceprint_ref: "vp-abc123", enrolled_at: "2026-08-29T10:00:00Z" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    vi.stubGlobal("fetch", fetchImpl);

    render(
      <VoiceprintEnrollment
        baseUrl="http://api.example"
        personId="person-dadi"
        getUserMedia={getUserMedia}
        createMediaRecorder={createMediaRecorder}
        clipDurationMs={5}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Record voiceprint sample/ }));
    await waitFor(() => expect(getUserMedia).toHaveBeenCalledWith({ audio: true }));
    expect(screen.getByRole("button", { name: /Recording/ })).toBeDisabled();

    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });

    expect(recorder.started).toBe(true);
    await waitFor(() => expect(screen.getByText(/Voiceprint recorded/)).toBeInTheDocument());
    expect(screen.getByText("vp-abc123")).toBeInTheDocument();

    // Real POST to the actual /enroll endpoint, JSON body — never the
    // old multipart-form shape.
    const [url, init] = fetchImpl.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("http://api.example/voice/persons/person-dadi/enroll");
    expect(init.method).toBe("POST");
    expect(init.headers).toEqual({ "Content-Type": "application/json" });
    const body = JSON.parse(init.body as string) as { audio_b64: string; mime_type: string };
    expect(typeof body.audio_b64).toBe("string");
    expect(body.audio_b64.length).toBeGreaterThan(0);
    expect(body.mime_type).toBe("audio/webm");
  });

  it("shows a real failure, never a fabricated success, when mic access fails", async () => {
    const getUserMedia = vi.fn().mockRejectedValue(new Error("no mic"));
    render(<VoiceprintEnrollment baseUrl="http://api.example" personId="person-dadi" getUserMedia={getUserMedia} />);

    fireEvent.click(screen.getByRole("button", { name: /Record voiceprint sample/ }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("no mic"));
  });

  it("names the household member being enrolled", () => {
    render(<VoiceprintEnrollment baseUrl="http://api.example" personId="person-dadi" />);
    expect(screen.getByText(/Dadi's voice/)).toBeInTheDocument();
  });
});
