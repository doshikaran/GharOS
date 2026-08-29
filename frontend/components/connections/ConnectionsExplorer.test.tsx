import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import type { ConnectionRecord } from "@/lib/connections";
import { ConnectionsExplorer } from "./ConnectionsExplorer";

const BASE = "https://api.example.com";

function jsonOk(body: unknown) {
  return {
    ok: true,
    status: 200,
    statusText: "OK",
    text: () => Promise.resolve(JSON.stringify(body)),
  } as Response;
}

const GOOGLE_ACTIVE: ConnectionRecord = {
  provider: "google",
  principal: "priya@example.com",
  granted_scopes: ["openid", "email", "https://www.googleapis.com/auth/gmail.readonly"],
  connected_at: "2026-08-29T10:00:00Z",
  last_scan_at: "2026-08-29T13:00:00Z",
  revoked_at: null,
};

class FakeEventSource {
  addEventListener(): void {}
  removeEventListener(): void {}
  close(): void {}
}

beforeEach(() => {
  vi.stubGlobal("EventSource", FakeEventSource as unknown as typeof EventSource);
});

afterEach(() => {
  vi.unstubAllGlobals();
  cleanup();
});

describe("ConnectionsExplorer", () => {
  it("shows a real, specific error when GET /connections fails, not a generic message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch: connection refused")));
    render(<ConnectionsExplorer baseUrl={BASE} />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not load your connected accounts");
    expect(alert).toHaveTextContent("connection refused");
  });

  it("disables the scan button, with a reason, when nothing is connected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonOk([])));
    render(<ConnectionsExplorer baseUrl={BASE} />);

    const button = await screen.findByRole("button", { name: /Scan the last 24 hours/ });
    expect(button).toBeDisabled();
    expect(screen.getByText(/Connect Gmail or Outlook above to enable a scan/)).toBeInTheDocument();
  });

  it("enables the scan button once an account is connected and names what it will scan", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonOk([GOOGLE_ACTIVE])));
    render(<ConnectionsExplorer baseUrl={BASE} />);

    const button = await screen.findByRole("button", { name: /Scan the last 24 hours/ });
    expect(button).toBeEnabled();
    expect(screen.getByText(/Will scan Gmail as/)).toHaveTextContent("priya@example.com");
    expect(screen.getAllByText("Connected").length).toBeGreaterThan(0);
    // Granted scopes are shown plainly.
    expect(screen.getByText("Read your Gmail (read-only)")).toBeInTheDocument();
  });

  it("posts to the disconnect endpoint and optimistically drops the connection", async () => {
    const fetchMock = vi.fn().mockImplementation((url: string, init?: RequestInit) => {
      if (url.endsWith("/connections") && (!init || init.method === "GET" || init.method === undefined)) {
        return Promise.resolve(jsonOk([GOOGLE_ACTIVE]));
      }
      if (url.includes("/disconnect")) {
        return Promise.resolve({ ok: true, status: 200, statusText: "OK", text: () => Promise.resolve("") } as Response);
      }
      return Promise.reject(new Error(`unexpected fetch ${url}`));
    });
    vi.stubGlobal("fetch", fetchMock);

    render(<ConnectionsExplorer baseUrl={BASE} />);

    const disconnect = await screen.findByRole("button", { name: "Disconnect" });
    disconnect.click();

    await waitFor(() =>
      expect(fetchMock).toHaveBeenCalledWith(
        `${BASE}/connections/google/priya%40example.com/disconnect`,
        expect.objectContaining({ method: "POST" }),
      ),
    );
  });
});
