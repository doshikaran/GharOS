import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, within } from "@testing-library/react";
import {
  DOCUMENT_INGEST_STATUSES,
  type DocumentIngestOutcome,
  type IngestionRunResult,
} from "@/lib/connections";
import { IngestionRunView, type IngestionRunViewState } from "./IngestionRunView";
import { ingestionStatusLabel } from "./IngestionStatusBadge";

afterEach(cleanup);

function outcome(status: DocumentIngestOutcome["status"], over: Partial<DocumentIngestOutcome> = {}): DocumentIngestOutcome {
  return {
    content_hash: `hash-${status}`,
    source: "gmail",
    status,
    source_document_id: `sd-${status}`,
    external_ref: `msg-${status}`,
    classified_type_id: "school_notice",
    new_node_ids: status === "ingested" ? ["node-a", "node-b"] : [],
    new_edge_ids: [],
    detail: status === "ingested" ? "" : `${status} detail`,
    ...over,
  };
}

function run(over: Partial<IngestionRunResult> = {}): IngestionRunResult {
  return {
    run_id: "run-1",
    idempotency_scope: "manual-scan:x",
    started_at: "2026-08-29T14:00:00Z",
    finished_at: "2026-08-29T14:00:06Z",
    sources_scanned: ["gmail", "outlook"],
    outcomes: [],
    new_node_ids: [],
    connector_failures: [],
    run_errors: [],
    ...over,
  };
}

function doneState(result: IngestionRunResult): IngestionRunViewState {
  return { phase: "done", run: result, liveNodeIds: [] };
}

describe("IngestionRunView", () => {
  it("renders every DocumentIngestStatus with a distinct label and data-status", () => {
    const outcomes = DOCUMENT_INGEST_STATUSES.map((status) => outcome(status));
    render(<IngestionRunView state={doneState(run({ outcomes, new_node_ids: ["node-a", "node-b"] }))} />);

    const seenLabels = new Set<string>();
    for (const status of DOCUMENT_INGEST_STATUSES) {
      const label = ingestionStatusLabel(status);
      expect(seenLabels.has(label)).toBe(false);
      seenLabels.add(label);
      // The badge text for this status is on screen...
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
      // ...and its row carries the status as a data attribute for the
      // per-status accent treatment.
      expect(document.querySelector(`li[data-status="${status}"]`)).not.toBeNull();
    }
    // Six distinct labels for six statuses — nothing collapsed together.
    expect(seenLabels.size).toBe(DOCUMENT_INGEST_STATUSES.length);
  });

  it("links each INGESTED new node id into /graph deep-linked to the inspector", () => {
    const ingested = outcome("ingested", { new_node_ids: ["ob-77", "person-9"] });
    render(<IngestionRunView state={doneState(run({ outcomes: [ingested], new_node_ids: ["ob-77", "person-9"] }))} />);

    expect(screen.getByRole("link", { name: "ob-77" })).toHaveAttribute("href", "/graph?node=ob-77");
    expect(screen.getByRole("link", { name: "person-9" })).toHaveAttribute("href", "/graph?node=person-9");
  });

  it("renders an is_auth_failure connector failure as a reconnect prompt, not an empty state", () => {
    const state = doneState(
      run({
        outcomes: [],
        connector_failures: [
          { source: "gmail", principal: "a@example.com", reason: "refresh token expired", is_auth_failure: true },
        ],
      }),
    );
    const onReconnect = vi.fn();
    render(<IngestionRunView state={state} onReconnect={onReconnect} />);

    const prompt = screen.getByTestId("reconnect-prompt");
    expect(within(prompt).getByText(/refresh token expired/)).toBeInTheDocument();
    // Not "no documents were found" — an auth failure is never a silent empty scan.
    expect(screen.queryByText(/No documents were found/i)).not.toBeInTheDocument();

    within(prompt).getByRole("button", { name: /Reconnect/ }).click();
    expect(onReconnect).toHaveBeenCalledWith("google");
  });

  it("shows a transient (non-auth) connector failure distinctly from an auth one", () => {
    const state = doneState(
      run({
        connector_failures: [
          { source: "outlook", principal: "b@example.com", reason: "Graph 503 after backoff", is_auth_failure: false },
        ],
      }),
    );
    render(<IngestionRunView state={state} />);
    expect(screen.getByText(/not an authorisation issue/i)).toBeInTheDocument();
    expect(screen.getByText(/Graph 503 after backoff/)).toBeInTheDocument();
    expect(screen.queryByTestId("reconnect-prompt")).not.toBeInTheDocument();
  });

  it("surfaces run_errors as a distinct 'partially trustworthy' block", () => {
    render(
      <IngestionRunView
        state={doneState(run({ outcomes: [outcome("ingested")], new_node_ids: ["node-a", "node-b"], run_errors: ["audit log write failed"] }))}
      />,
    );
    const block = screen.getByTestId("run-errors");
    expect(within(block).getByText(/audit log write failed/)).toBeInTheDocument();
  });

  it("renders the reconnect-required phase as a reconnect prompt", () => {
    render(
      <IngestionRunView
        state={{ phase: "reconnect-required", provider: "microsoft", principal: "b@example.com", message: "Reconnect Outlook" }}
      />,
    );
    expect(screen.getByTestId("reconnect-prompt")).toBeInTheDocument();
    expect(screen.getByText("Reconnect Outlook")).toBeInTheDocument();
  });

  it("renders the error phase with the real message and detail, not a generic error", () => {
    render(<IngestionRunView state={{ phase: "error", message: "The server returned an error: HTTP 500", detail: "traceback-ish" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("HTTP 500");
    expect(screen.getByText("traceback-ish")).toBeInTheDocument();
  });

  it("shows a running indicator with elapsed time while a scan is in flight", () => {
    render(
      <IngestionRunView
        state={{ phase: "running", startedAtMs: 1_000, liveNodeIds: ["n1", "n2"] }}
        now={() => 4_000}
      />,
    );
    expect(screen.getByText(/Scanning/)).toBeInTheDocument();
    expect(screen.getByText(/2 new nodes have arrived/)).toBeInTheDocument();
  });

  it("shows an idle hint before any scan has run", () => {
    render(<IngestionRunView state={{ phase: "idle" }} />);
    expect(screen.getByText(/No scan has run yet/)).toBeInTheDocument();
  });
});
