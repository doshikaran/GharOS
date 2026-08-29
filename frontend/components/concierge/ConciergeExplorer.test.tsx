import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { GraphSnapshot } from "@/lib/graph-types";
import { AARAV_ID } from "@/lib/concierge";
import { ConciergeExplorer } from "./ConciergeExplorer";

const snapshot: GraphSnapshot = {
  nodes: [
    {
      id: AARAV_ID,
      type: "PERSON",
      label: "Aarav",
      derivation: "extracted",
      confidence: 0.9,
      source_document_id: "doc-school-whatsapp",
      region: "header",
      created_at: "2026-08-22T09:00:00Z",
      fields: { display_name: "Aarav" },
    },
  ],
  edges: [],
};

function stubFetch(response: GraphSnapshot | null) {
  vi.stubGlobal(
    "fetch",
    vi.fn().mockImplementation(() =>
      response
        ? Promise.resolve({ ok: true, json: () => Promise.resolve(response) } as Response)
        : Promise.reject(new TypeError("Failed to fetch")),
    ),
  );
}

async function waitForReady() {
  await waitFor(() => expect(screen.getByText(/Clarify, graph-first/)).toBeInTheDocument());
}

describe("ConciergeExplorer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the snapshot resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the household's current graph");
  });

  it("degrades to fixed household names, still renders, when the live fetch fails", async () => {
    stubFetch(null);
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getByRole("alert")).toHaveTextContent(/Could not reach the live graph/);
    expect(screen.getAllByText(/Aarav/).length).toBeGreaterThan(0);
  });

  it("never shows the call transcript or a booking outcome before the approval gate is approved", async () => {
    stubFetch(snapshot);
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.queryByLabelText("Live call transcript")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Booking confirmation")).not.toBeInTheDocument();
  });

  it("reveals the hero call transcript and booking outcome only after Approve is clicked", async () => {
    stubFetch(snapshot);
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    await waitForReady();
    fireEvent.click(screen.getByRole("button", { name: /approve this call/i }));
    expect(screen.getByLabelText("Live call transcript")).toBeInTheDocument();
    expect(screen.getByLabelText("Booking confirmation")).toBeInTheDocument();
    expect(screen.getByText("Booked & verified")).toBeInTheDocument();
  });

  it("renders both safeguard scenarios with their real, distinct 'not recorded' outcomes", async () => {
    stubFetch(snapshot);
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getAllByText("Could not verify, not recorded").length).toBe(2);
  });

  it("renders the retry decision with a real retryAfter time for the follow-up scenario", async () => {
    stubFetch(snapshot);
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getByText("No answer")).toBeInTheDocument();
    expect(screen.getByText(/Next attempt authorised at/)).toBeInTheDocument();
  });

  it("states plainly, up front, that every call is a real sandboxed text conversation, never audio", async () => {
    stubFetch(snapshot);
    render(<ConciergeExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getByText(/never synthesized audio/i)).toBeInTheDocument();
    expect(screen.getByText(/deferred to Phase 13/)).toBeInTheDocument();
  });
});
