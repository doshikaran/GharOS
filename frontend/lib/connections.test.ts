import { afterEach, describe, expect, it, vi } from "vitest";
import {
  computeStatusCounts,
  DOCUMENT_INGEST_STATUSES,
  fetchConnections,
  ingestionSourceLabel,
  newIdempotencyScope,
  oauthStartUrl,
  parseConnectionRecords,
  parseIngestionRunResult,
  providerScanKinds,
  scopePlainLabel,
  startScan,
  type DocumentIngestOutcome,
  type IngestionRunResult,
} from "./connections";

function fakeResponse(body: string, init: { ok: boolean; status: number; statusText: string }) {
  return {
    ok: init.ok,
    status: init.status,
    statusText: init.statusText,
    text: () => Promise.resolve(body),
  } as Response;
}

function outcome(over: Partial<DocumentIngestOutcome>): DocumentIngestOutcome {
  return {
    content_hash: "hash",
    source: "gmail",
    status: "ingested",
    source_document_id: "sd-1",
    external_ref: "msg-1",
    classified_type_id: "school_notice",
    new_node_ids: ["n-1"],
    new_edge_ids: ["e-1"],
    detail: "",
    ...over,
  };
}

const RUN: IngestionRunResult = {
  run_id: "run-1",
  idempotency_scope: "manual-scan:x",
  started_at: "2026-08-29T14:00:00Z",
  finished_at: "2026-08-29T14:00:08Z",
  sources_scanned: ["gmail", "outlook"],
  outcomes: [outcome({}), outcome({ content_hash: "h2", status: "duplicate_skipped", new_node_ids: [] })],
  new_node_ids: ["n-1"],
  connector_failures: [],
  run_errors: [],
};

describe("connections wire helpers", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("labels every source kind and scan-relevant provider mapping", () => {
    expect(ingestionSourceLabel("gmail")).toBe("Gmail");
    expect(ingestionSourceLabel("drive_picker")).toBe("Google Drive");
    expect(providerScanKinds("google")).toEqual(["gmail"]);
    expect(providerScanKinds("microsoft")).toEqual(["outlook"]);
  });

  it("gives plain-language labels for known scopes and passes unknown ones through", () => {
    expect(scopePlainLabel("https://www.googleapis.com/auth/gmail.readonly")).toBe("Read your Gmail (read-only)");
    expect(scopePlainLabel("Mail.Read")).toBe("Read your Outlook mail");
    expect(scopePlainLabel("custom.scope")).toBe("custom.scope");
  });

  it("builds the OAuth consent-start URL against the API base", () => {
    expect(oauthStartUrl("https://api.example.com", "google")).toBe(
      "https://api.example.com/oauth/google/start",
    );
  });

  it("computes a per-status tally from outcomes for every status key", () => {
    const counts = computeStatusCounts([
      outcome({ status: "ingested" }),
      outcome({ status: "ingested" }),
      outcome({ status: "extraction_failed" }),
      outcome({ status: "registry_gap" }),
    ]);
    expect(counts.ingested).toBe(2);
    expect(counts.extraction_failed).toBe(1);
    expect(counts.registry_gap).toBe(1);
    expect(counts.error).toBe(0);
    // every enum member is present as a key
    for (const status of DOCUMENT_INGEST_STATUSES) {
      expect(counts).toHaveProperty(status);
    }
  });

  it("newIdempotencyScope carries the prefix and an ISO timestamp", () => {
    const scope = newIdempotencyScope("manual-scan");
    expect(scope.startsWith("manual-scan:")).toBe(true);
    expect(() => new Date(scope.slice("manual-scan:".length)).toISOString()).not.toThrow();
  });
});

describe("parseIngestionRunResult", () => {
  it("accepts a well-formed run result", () => {
    expect(parseIngestionRunResult(JSON.parse(JSON.stringify(RUN)))).toEqual(RUN);
  });

  it("rejects a result missing run_id", () => {
    const bad = { ...JSON.parse(JSON.stringify(RUN)), run_id: undefined };
    expect(parseIngestionRunResult(bad)).toBeNull();
  });

  it("rejects an outcome with an unknown status", () => {
    const bad = JSON.parse(JSON.stringify(RUN));
    bad.outcomes[0].status = "made_up";
    expect(parseIngestionRunResult(bad)).toBeNull();
  });

  it("defaults optional connector_failures / run_errors to empty arrays", () => {
    const raw = JSON.parse(JSON.stringify(RUN));
    delete raw.connector_failures;
    delete raw.run_errors;
    const parsed = parseIngestionRunResult(raw);
    expect(parsed?.connector_failures).toEqual([]);
    expect(parsed?.run_errors).toEqual([]);
  });
});

describe("parseConnectionRecords", () => {
  it("accepts a well-formed connection array with null last_scan/revoked", () => {
    const raw = [
      {
        provider: "google",
        principal: "a@example.com",
        granted_scopes: ["openid", "https://www.googleapis.com/auth/gmail.readonly"],
        connected_at: "2026-08-29T10:00:00Z",
        last_scan_at: null,
        revoked_at: null,
      },
    ];
    expect(parseConnectionRecords(raw)).toHaveLength(1);
  });

  it("rejects a record with a bad provider", () => {
    const raw = [
      {
        provider: "yahoo",
        principal: "a@example.com",
        granted_scopes: [],
        connected_at: "2026-08-29T10:00:00Z",
        last_scan_at: null,
        revoked_at: null,
      },
    ];
    expect(parseConnectionRecords(raw)).toBeNull();
  });
});

describe("fetchConnections", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns a typed network failure with the real message, never a generic one", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("Failed to fetch: DNS")),
    );
    const result = await fetchConnections("https://api.example.com");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.kind).toBe("network");
      expect(result.message).toContain("DNS");
    }
  });

  it("reports a non-2xx as a distinct http-error with the status and body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse("boom", { ok: false, status: 503, statusText: "Service Unavailable" })),
    );
    const result = await fetchConnections("https://api.example.com");
    expect(result.ok).toBe(false);
    if (!result.ok) {
      expect(result.kind).toBe("http-error");
      expect(result.httpStatus).toBe(503);
      expect(result.body).toBe("boom");
    }
  });
});

describe("startScan", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("POSTs the documented JSON body to /ingest", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(fakeResponse(JSON.stringify(RUN), { ok: true, status: 200, statusText: "OK" }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await startScan("https://api.example.com", {
      sources: ["gmail", "outlook"],
      windowSeconds: 86_400,
      principal: "a@example.com",
      meta: { idempotencyScope: "manual-scan:x", triggeredBy: "person-priya", householdId: "gharos-demo-household" },
    });

    expect(result.status).toBe("ok");
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("https://api.example.com/ingest");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      sources: ["gmail", "outlook"],
      window_seconds: 86_400,
      principal: "a@example.com",
      idempotency_scope: "manual-scan:x",
      triggered_by: "person-priya",
      household_id: "gharos-demo-household",
    });
  });

  it("maps a 409 precondition failure to reconnect-required with the provider", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        fakeResponse('{"detail":"Connect Google first","provider":"google","principal":"a@example.com"}', {
          ok: false,
          status: 409,
          statusText: "Conflict",
        }),
      ),
    );
    const result = await startScan("https://api.example.com", {
      sources: ["gmail"],
      windowSeconds: 86_400,
      principal: "a@example.com",
      meta: { idempotencyScope: "s", triggeredBy: "person-priya", householdId: "h" },
    });
    expect(result).toEqual({
      status: "reconnect-required",
      provider: "google",
      principal: "a@example.com",
      message: "Connect Google first",
    });
  });

  it("reports a malformed 200 body as a distinct invalid-json error", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(fakeResponse("not json", { ok: true, status: 200, statusText: "OK" })),
    );
    const result = await startScan("https://api.example.com", {
      sources: ["gmail"],
      windowSeconds: 86_400,
      principal: "a@example.com",
      meta: { idempotencyScope: "s", triggeredBy: "person-priya", householdId: "h" },
    });
    expect(result.status).toBe("error");
    if (result.status === "error") expect(result.kind).toBe("invalid-json");
  });
});
