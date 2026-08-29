import { afterEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { GraphSnapshot } from "@/lib/graph-types";
import { DADI_NAP_CONSTRAINT_ID } from "@/lib/intention-action";
import { IntentionActionExplorer } from "./IntentionActionExplorer";

const snapshot: GraphSnapshot = {
  nodes: [
    {
      id: "person-priya",
      type: "PERSON",
      label: "Priya",
      derivation: "extracted",
      confidence: 0.9,
      source_document_id: "doc-school-whatsapp",
      region: "header",
      created_at: "2026-08-22T09:00:00Z",
      fields: { display_name: "Priya" },
    },
    {
      id: "person-dadi",
      type: "PERSON",
      label: "Dadi",
      derivation: "extracted",
      confidence: 0.9,
      source_document_id: "doc-pharmacy-sms",
      region: "recipient",
      created_at: "2026-08-22T09:00:00Z",
      fields: { display_name: "Dadi" },
    },
    {
      id: DADI_NAP_CONSTRAINT_ID,
      type: "CONSTRAINT",
      label: "Schedule constraint",
      derivation: "inferred",
      confidence: 0.7,
      source_document_id: "doc-pharmacy-sms",
      region: "msg-3",
      created_at: "2026-08-22T09:00:00Z",
      fields: {
        kind: "schedule",
        severity: "soft",
        structured: { days_of_week: "daily", start_time: "14:00", end_time: "16:00" },
      },
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
  await waitFor(() => expect(screen.getByText("The six-type blocker taxonomy")).toBeInTheDocument());
}

describe("IntentionActionExplorer", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("shows a loading state before the snapshot resolves", () => {
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise(() => {})));
    render(<IntentionActionExplorer baseUrl="http://api.example" />);
    expect(screen.getByRole("status")).toHaveTextContent("Loading the household's current graph");
  });

  it("degrades to fixed household names, still renders, when the live fetch fails", async () => {
    stubFetch(null);
    render(<IntentionActionExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getByRole("alert")).toHaveTextContent(/Could not reach the live graph/);
    // Falls back to the real household's own fixed names.
    expect(screen.getAllByText("Priya").length).toBeGreaterThan(0);
  });

  it("renders the stale-obligation detection unprompted", async () => {
    stubFetch(snapshot);
    render(<IntentionActionExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getByText("124 days stale")).toBeInTheDocument();
    expect(screen.getAllByText("Book Aarav's dental check-up").length).toBeGreaterThan(0);
  });

  it("renders the diagnosis, four unblock outcomes, and slippage escalation", async () => {
    stubFetch(snapshot);
    render(<IntentionActionExplorer baseUrl="http://api.example" />);
    await waitForReady();
    expect(screen.getByText("What actually happened, the four unblock outcomes")).toBeInTheDocument();
    expect(screen.getByText(/Aarav's dental check-up, re-diagnosed, then escalated/)).toBeInTheDocument();
    expect(screen.getByText("Untouched for months, now moving")).toBeInTheDocument();
  });

  it("Gate 9's literal requirement: submitting a correction visibly updates the friction profile in this same session", async () => {
    stubFetch(snapshot);
    render(<IntentionActionExplorer baseUrl="http://api.example" />);
    await waitForReady();

    // Before: Priya's real, live-named friction profile section shows the
    // aversion pattern at its starting support count.
    const frictionSection = screen.getByLabelText("Friction profile");
    expect(within(frictionSection).getByText("seen 3 times")).toBeInTheDocument();
    expect(within(frictionSection).queryByText("seen 4 times")).not.toBeInTheDocument();

    // Submit a correction on the eye check-up's information diagnosis,
    // re-typing it as aversion — the same type Priya already has a
    // pattern for.
    fireEvent.change(screen.getByLabelText("Actual blocker type"), { target: { value: "aversion" } });
    fireEvent.change(screen.getByLabelText("Correction note"), {
      target: { value: "The number was found in ten seconds, that was never the real hold-up." },
    });
    fireEvent.click(screen.getByRole("button", { name: "Submit correction" }));

    // After: the same friction-profile section, in the same render pass,
    // now shows 4 — the correction's effect is directly observable.
    expect(within(frictionSection).getByText("seen 4 times")).toBeInTheDocument();
    expect(within(frictionSection).queryByText("seen 3 times")).not.toBeInTheDocument();
    expect(within(frictionSection).getByText("Just updated")).toBeInTheDocument();

    // The correction form itself now shows its confirmation state, plainly
    // stating there is no live write endpoint yet.
    expect(screen.getByText("Correction recorded")).toBeInTheDocument();
    expect(screen.getByText(/no live write endpoint yet/)).toBeInTheDocument();
  });

  it("computes the window-blocker demo's person-availability verdicts from the real live Dadi nap constraint", async () => {
    stubFetch(snapshot);
    render(<IntentionActionExplorer baseUrl="http://api.example" />);
    await waitForReady();
    // The Thursday candidate (clear of every constraint) is recommended.
    expect(screen.getByText("Recommended")).toBeInTheDocument();
    // The Monday candidate overlaps the real, live nap window.
    expect(screen.getByText("Dadi: Soft, avoid if possible")).toBeInTheDocument();
  });
});
