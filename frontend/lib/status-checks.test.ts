import { afterEach, describe, expect, it, vi } from "vitest";
import { runStatusCheck, type StatusCheckDefinition } from "./status-checks";

const DEFINITION: StatusCheckDefinition = {
  id: "health",
  label: "API health",
  description: "test",
  path: "/health",
  method: "GET",
};

function jsonResponse(body: string, init: { ok: boolean; status: number; statusText: string }) {
  return {
    ok: init.ok,
    status: init.status,
    statusText: init.statusText,
    text: () => Promise.resolve(body),
  } as Response;
}

describe("runStatusCheck", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it("reports a real success with the parsed payload on a 2xx JSON response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse('{"status":"ok"}', { ok: true, status: 200, statusText: "OK" }),
      ),
    );

    const result = await runStatusCheck(DEFINITION, "http://api.example");

    expect(result.status).toBe("success");
    if (result.status === "success") {
      expect(result.httpStatus).toBe(200);
      expect(result.data).toEqual({ status: "ok" });
    }
  });

  it("reports a real http-error failure, with the response body, on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        jsonResponse('{"detail":"Vertex AI call failed"}', {
          ok: false,
          status: 502,
          statusText: "Bad Gateway",
        }),
      ),
    );

    const result = await runStatusCheck(DEFINITION, "http://api.example");

    expect(result.status).toBe("failure");
    if (result.status === "failure") {
      expect(result.kind).toBe("http-error");
      expect(result.httpStatus).toBe(502);
      expect(result.message).toContain("502");
      expect(result.body).toEqual({ detail: "Vertex AI call failed" });
    }
  });

  it("reports a real network-error failure without hiding the underlying message", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const result = await runStatusCheck(DEFINITION, "http://api.example");

    expect(result.status).toBe("failure");
    if (result.status === "failure") {
      expect(result.kind).toBe("network");
      expect(result.message).toBe("Failed to fetch");
    }
  });

  it("reports an invalid-json failure when a 2xx response body isn't parseable JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(jsonResponse("not json", { ok: true, status: 200, statusText: "OK" })),
    );

    const result = await runStatusCheck(DEFINITION, "http://api.example");

    expect(result.status).toBe("failure");
    if (result.status === "failure") {
      expect(result.kind).toBe("invalid-json");
      expect(result.body).toBe("not json");
    }
  });

  it("reports a timeout failure when the request never resolves", async () => {
    vi.useFakeTimers();
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: { signal?: AbortSignal }) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    const pending = runStatusCheck(DEFINITION, "http://api.example");
    await vi.advanceTimersByTimeAsync(10_000);
    const result = await pending;

    expect(result.status).toBe("failure");
    if (result.status === "failure") {
      expect(result.kind).toBe("timeout");
    }
  });
});
