import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { StatusBoard } from "./StatusBoard";

function jsonResponse(body: unknown, init: { ok: boolean; status: number; statusText: string }) {
  return {
    ok: init.ok,
    status: init.status,
    statusText: init.statusText,
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

describe("StatusBoard", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("renders a pending card per check before any fetch resolves", () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(() => new Promise<Response>(() => {})), // never resolves within this test
    );

    render(<StatusBoard />);

    expect(screen.getByText("API health")).toBeInTheDocument();
    expect(screen.getByText("Gemini via Vertex AI")).toBeInTheDocument();
    expect(screen.getByText("Google ADK tool invocation")).toBeInTheDocument();
    expect(screen.getAllByText("Checking…")).toHaveLength(3);
  });

  it("renders each check's real success payload once its fetch resolves", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/health")) {
          return Promise.resolve(jsonResponse({ status: "ok" }, { ok: true, status: 200, statusText: "OK" }));
        }
        if (url.endsWith("/debug/gemini-ping")) {
          return Promise.resolve(
            jsonResponse(
              { response_text: "pong", model_tier: "flash", model_name: "gemini-2.5-flash" },
              { ok: true, status: 200, statusText: "OK" },
            ),
          );
        }
        return Promise.resolve(
          jsonResponse(
            {
              response_text: "It is now ...",
              tool_invoked: "get_current_utc_time",
              tool_result: { utc_time: "2026-08-22T00:00:00Z" },
              model_name: "gemini-2.5-pro",
            },
            { ok: true, status: 200, statusText: "OK" },
          ),
        );
      }),
    );

    render(<StatusBoard />);

    await waitFor(() => {
      expect(screen.getAllByText("Reachable")).toHaveLength(3);
    });
    expect(screen.getByText(/"status": "ok"/)).toBeInTheDocument();
    expect(screen.getByText(/get_current_utc_time/)).toBeInTheDocument();
    expect(screen.getByText(/All 3 checks reached the deployed backend successfully\./)).toBeInTheDocument();
  });

  it("renders the real error detail, never a generic message, on a failed check, and leaves the others visibly distinct", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/health")) {
          return Promise.reject(new TypeError("Failed to fetch"));
        }
        return Promise.resolve(
          jsonResponse({ response_text: "pong" }, { ok: true, status: 200, statusText: "OK" }),
        );
      }),
    );

    render(<StatusBoard />);

    await waitFor(() => {
      expect(screen.getByText("Failed")).toBeInTheDocument();
    });
    expect(screen.getByText("Failed to fetch")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("Failed to fetch");
    await waitFor(() => {
      expect(screen.getAllByText("Reachable")).toHaveLength(2);
    });
    expect(
      screen.getByText(/1 of 3 checks failed to reach the deployed backend\./),
    ).toBeInTheDocument();
  });

  it("shows a non-2xx response's real HTTP status and body instead of hiding it", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        if (url.endsWith("/debug/adk-demo")) {
          return Promise.resolve(
            jsonResponse(
              { detail: "Vertex AI call failed" },
              { ok: false, status: 502, statusText: "Bad Gateway" },
            ),
          );
        }
        return Promise.resolve(jsonResponse({ ok: true }, { ok: true, status: 200, statusText: "OK" }));
      }),
    );

    render(<StatusBoard />);

    await waitFor(() => {
      expect(screen.getByText(/HTTP error response · HTTP 502/)).toBeInTheDocument();
    });
    expect(screen.getByText(/Vertex AI call failed/)).toBeInTheDocument();
  });

  it("reads the configured NEXT_PUBLIC_API_BASE_URL and calls each endpoint against it", async () => {
    vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://gharos-api-971309809251.asia-south1.run.app");
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ status: "ok" }, { ok: true, status: 200, statusText: "OK" }));
    vi.stubGlobal("fetch", fetchMock);

    render(<StatusBoard />);

    expect(
      screen.getByText("https://gharos-api-971309809251.asia-south1.run.app", { exact: false }),
    ).toBeInTheDocument();
    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        "https://gharos-api-971309809251.asia-south1.run.app/health",
        expect.anything(),
      );
    });
  });
});
