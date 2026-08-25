import { afterEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SourceRegionViewer } from "./SourceRegionViewer";

function textResponse(text: string, contentType: string) {
  const bytes = new TextEncoder().encode(text);
  return {
    ok: true,
    headers: new Headers({ "content-type": contentType }),
    arrayBuffer: () => Promise.resolve(bytes.buffer),
  } as unknown as Response;
}

describe("SourceRegionViewer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the fetch resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<SourceRegionViewer baseUrl="http://api.example" documentId="doc-1" region="0-5" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading source document");
  });

  it("highlights the exact byte-offset span for a text document", async () => {
    const text = "The vendor offers a slot tomorrow.";
    const start = text.indexOf("slot");
    const end = start + "slot".length;
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(textResponse(text, "text/plain")));

    render(<SourceRegionViewer baseUrl="http://api.example" documentId="doc-1" region={`${start}-${end}`} />);

    await waitFor(() => expect(screen.getByText("slot", { selector: "mark" })).toBeInTheDocument());
    expect(screen.getByText(/The vendor offers a/)).toBeInTheDocument();
  });

  it("shows a real error, not a silent blank panel, when the fetch fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    render(<SourceRegionViewer baseUrl="http://api.example" documentId="doc-1" region="0-5" />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load the source document/));
  });

  it("shows a malformed-region error rather than crashing on a bad region string", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(textResponse("hello", "text/plain")));

    render(<SourceRegionViewer baseUrl="http://api.example" documentId="doc-1" region="not-a-region" />);

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Malformed region/));
  });

  it("reports a content-type / region-convention mismatch honestly instead of guessing", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(textResponse("hello", "text/plain")));

    render(<SourceRegionViewer baseUrl="http://api.example" documentId="doc-1" region="page=1;bbox=1,1,2,2" />);

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/does not match its region locator convention/),
    );
  });
});
