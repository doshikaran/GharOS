import { afterEach, describe, expect, it, vi } from "vitest";
import { documentRawUrl, fetchDocumentRaw, fetchGraphSnapshot, fetchJustification, GraphApiError } from "./graph-api";

describe("fetchGraphSnapshot", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed snapshot on a 2xx response", async () => {
    const snapshot = { nodes: [], edges: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(snapshot) } as Response),
    );

    const result = await fetchGraphSnapshot("http://api.example");
    expect(result).toEqual(snapshot);
  });

  it("throws a GraphApiError with the real status on a non-2xx response", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 503,
        statusText: "Service Unavailable",
        text: () => Promise.resolve(""),
      } as Response),
    );

    await expect(fetchGraphSnapshot("http://api.example")).rejects.toMatchObject({
      name: "GraphApiError",
      status: 503,
    });
  });

  it("throws a GraphApiError, not a raw exception, on a network failure, never a fabricated success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    await expect(fetchGraphSnapshot("http://api.example")).rejects.toBeInstanceOf(GraphApiError);
  });
});

describe("fetchJustification", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("hits the correct URL and returns the parsed response", async () => {
    const response = { root_node_id: "n1", steps: [], source_documents: [] };
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(response) } as Response);
    vi.stubGlobal("fetch", fetchMock);

    const result = await fetchJustification("http://api.example", "n1");
    expect(result).toEqual(response);
    expect(fetchMock).toHaveBeenCalledWith("http://api.example/graph/nodes/n1/justification");
  });

  it("URL-encodes the node id", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue({ ok: true, json: () => Promise.resolve({ root_node_id: "x", steps: [], source_documents: [] }) } as Response);
    vi.stubGlobal("fetch", fetchMock);

    await fetchJustification("http://api.example", "n/1 x");
    expect(fetchMock).toHaveBeenCalledWith("http://api.example/graph/nodes/n%2F1%20x/justification");
  });
});

describe("documentRawUrl", () => {
  it("builds the raw-document URL", () => {
    expect(documentRawUrl("http://api.example", "doc-1")).toBe("http://api.example/documents/doc-1/raw");
  });
});

describe("fetchDocumentRaw", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the real Content-Type header and raw bytes", async () => {
    const bytes = new TextEncoder().encode("hello world");
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: true,
        headers: new Headers({ "content-type": "text/plain" }),
        arrayBuffer: () => Promise.resolve(bytes.buffer),
      } as unknown as Response),
    );

    const result = await fetchDocumentRaw("http://api.example", "doc-1");
    expect(result.contentType).toBe("text/plain");
    expect(new TextDecoder().decode(result.bytes)).toBe("hello world");
  });

  it("throws a GraphApiError on a 404", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({ ok: false, status: 404, statusText: "Not Found" } as Response),
    );

    await expect(fetchDocumentRaw("http://api.example", "missing")).rejects.toMatchObject({ status: 404 });
  });
});
