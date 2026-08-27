import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { GraphSnapshot } from "@/lib/graph-types";
import { LedgerExplorer } from "./LedgerExplorer";

const { fetchDocumentRawMock } = vi.hoisted(() => ({ fetchDocumentRawMock: vi.fn() }));

vi.mock("@/lib/graph-api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/graph-api")>("@/lib/graph-api");
  return { ...actual, fetchDocumentRaw: fetchDocumentRawMock };
});

const snapshot: GraphSnapshot = {
  nodes: [
    {
      id: "ledger-maintenance-debit",
      type: "LEDGER_EVENT",
      label: "debit — INR 2500",
      derivation: "extracted",
      confidence: 0.9,
      source_document_id: "doc-society-notice",
      region: "payment-confirmation",
      created_at: "2026-08-22T06:00:00Z",
      fields: {
        kind: "debit",
        amount: 2500,
        currency: "INR",
        occurred_at: "2026-08-22T06:00:00Z",
        counterparty_raw: "SUNRISE SOCIETY MAINT",
      },
    },
    {
      id: "commitment-society-maintenance",
      type: "RECURRING_COMMITMENT",
      label: "Sunrise Society maintenance",
      derivation: "extracted",
      confidence: 0.9,
      source_document_id: "doc-society-notice",
      region: "whole-document",
      created_at: "2025-08-22T00:00:00Z",
      fields: {
        label: "Sunrise Society maintenance",
        counterparty: "Sunrise Apartments Society",
        amount: 2500,
        cadence: "monthly",
        price_history: [
          ["2025-08-22T00:00:00Z", 2300],
          ["2026-07-23T00:00:00Z", 2500],
        ],
        last_used_at: "2026-07-23T00:00:00Z",
        status: "active",
      },
    },
  ],
  edges: [
    {
      id: "e-belongs-1",
      type: "belongs_to",
      from_id: "ledger-maintenance-debit",
      to_id: "commitment-society-maintenance",
      derivation: "extracted",
      confidence: 0.9,
      is_conflict: false,
    },
  ],
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

describe("LedgerExplorer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    fetchDocumentRawMock.mockReset();
  });

  it("shows a loading state before the snapshot resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<LedgerExplorer baseUrl="http://api.example" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the household ledger");
  });

  it("shows a real error rather than a blank ledger when the snapshot fetch fails", async () => {
    stubFetch(null);
    render(<LedgerExplorer baseUrl="http://api.example" />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load the ledger/));
  });

  it("renders the live transaction and commitment data from /graph/snapshot", async () => {
    stubFetch(snapshot);
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1]) });
    render(<LedgerExplorer baseUrl="http://api.example" />);

    await screen.findByText("SUNRISE SOCIETY MAINT");
    // "Sunrise Society maintenance" legitimately renders in more than one
    // place (the commitment row, its filter-select option, and the linked
    // transaction's commitment tag) — assert it is present at all, not that
    // it is unique.
    expect(screen.getAllByText("Sunrise Society maintenance").length).toBeGreaterThan(0);
  });

  it("renders the recovered-money counter, leakage surface, dispute surface, and payroll review from fixture data", async () => {
    stubFetch(snapshot);
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1]) });
    render(<LedgerExplorer baseUrl="http://api.example" />);

    await screen.findByText("SUNRISE SOCIETY MAINT");
    expect(screen.getByText(/Recovered-money counter/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: /CloudTV Premium/ })).toBeInTheDocument();
    expect(screen.getByText("August society maintenance debit")).toBeInTheDocument();
    expect(screen.getByText("2026-08 payroll")).toBeInTheDocument();
  });

  it("proposing a mandate cancellation on a live commitment routes through the real Approval Gate end to end", async () => {
    stubFetch(snapshot);
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1]) });
    render(<LedgerExplorer baseUrl="http://api.example" />);

    await screen.findByText("SUNRISE SOCIETY MAINT");
    expect(screen.queryByText("Mandate cancellation — approval gate")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Propose cancelling this mandate" }));

    expect(await screen.findByText("Mandate cancellation — approval gate")).toBeInTheDocument();
    expect(screen.getByText(/Cancel the recurring mandate for Sunrise Society maintenance/)).toBeInTheDocument();
    expect(screen.getByText(/Cancellation proposed/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Approve" }));
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveTextContent("Confirm approval — this executes now");
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm and execute" }));

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("filters the visible transactions by kind", async () => {
    stubFetch(snapshot);
    fetchDocumentRawMock.mockResolvedValue({ contentType: "image/jpeg", bytes: new Uint8Array([1]) });
    render(<LedgerExplorer baseUrl="http://api.example" />);

    await screen.findByText("SUNRISE SOCIETY MAINT");
    fireEvent.click(screen.getByRole("button", { name: "Debit" }));
    await waitFor(() => expect(screen.queryByText("SUNRISE SOCIETY MAINT")).not.toBeInTheDocument());
    expect(screen.getByText("No transactions match the current filters.")).toBeInTheDocument();
  });
});
