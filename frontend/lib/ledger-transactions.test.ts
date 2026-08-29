import { describe, expect, it, vi } from "vitest";
import type { GraphEdge, GraphNode } from "./graph-types";
import {
  UNLINKED_COMMITMENT_FILTER,
  buildLedgerView,
  filterTransactions,
  type LedgerTransactionRow,
} from "./ledger-transactions";

function ledgerEventNode(overrides: Partial<GraphNode> & { id: string }): GraphNode {
  return {
    type: "LEDGER_EVENT",
    label: "Debit, INR 100",
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: "doc-1",
    region: "0-10",
    created_at: "2026-08-01T00:00:00Z",
    fields: {
      kind: "debit",
      amount: 100,
      currency: "INR",
      occurred_at: "2026-08-01T00:00:00Z",
      counterparty_raw: "SOME VENDOR",
    },
    ...overrides,
  };
}

function commitmentNode(overrides: Partial<GraphNode> & { id: string }): GraphNode {
  return {
    type: "RECURRING_COMMITMENT",
    label: "Some subscription",
    derivation: "extracted",
    confidence: 0.9,
    source_document_id: "doc-2",
    region: "whole-document",
    created_at: "2026-08-01T00:00:00Z",
    fields: {
      label: "Some subscription",
      counterparty: "Some Vendor",
      amount: 500,
      cadence: "monthly",
      price_history: [
        ["2025-08-01T00:00:00Z", 450],
        ["2026-07-01T00:00:00Z", 500],
      ],
      last_used_at: "2026-07-15T00:00:00Z",
      status: "active",
    },
    ...overrides,
  };
}

describe("buildLedgerView", () => {
  it("extracts every LEDGER_EVENT and RECURRING_COMMITMENT node, ignoring every other node type", () => {
    const nodes: GraphNode[] = [
      ledgerEventNode({ id: "ledger-1" }),
      commitmentNode({ id: "commitment-1" }),
      {
        id: "person-1",
        type: "PERSON",
        label: "Priya",
        derivation: "extracted",
        confidence: 0.9,
        source_document_id: null,
        region: null,
        created_at: null,
        fields: {},
      },
    ];
    const view = buildLedgerView(nodes, []);
    expect(view.transactions).toHaveLength(1);
    expect(view.commitments).toHaveLength(1);
    expect(view.transactions[0].id).toBe("ledger-1");
    expect(view.commitments[0].id).toBe("commitment-1");
  });

  it("resolves a transaction's commitment via a real `belongs_to` edge", () => {
    const nodes: GraphNode[] = [
      ledgerEventNode({ id: "ledger-maintenance-debit" }),
      commitmentNode({ id: "commitment-society-maintenance" }),
    ];
    const edges: GraphEdge[] = [
      {
        id: "e-belongs-1",
        type: "belongs_to",
        from_id: "ledger-maintenance-debit",
        to_id: "commitment-society-maintenance",
        derivation: "extracted",
        confidence: 0.9,
        is_conflict: false,
      },
    ];
    const view = buildLedgerView(nodes, edges);
    expect(view.transactions[0].commitmentId).toBe("commitment-society-maintenance");
  });

  it("leaves commitmentId null for a transaction with no belongs_to edge", () => {
    const view = buildLedgerView([ledgerEventNode({ id: "ledger-unlinked" })], []);
    expect(view.transactions[0].commitmentId).toBeNull();
  });

  it("sorts transactions newest-first", () => {
    const nodes: GraphNode[] = [
      ledgerEventNode({ id: "older", fields: { kind: "debit", amount: 1, currency: "INR", occurred_at: "2026-01-01T00:00:00Z", counterparty_raw: "A" } }),
      ledgerEventNode({ id: "newer", fields: { kind: "debit", amount: 1, currency: "INR", occurred_at: "2026-08-01T00:00:00Z", counterparty_raw: "B" } }),
    ];
    const view = buildLedgerView(nodes, []);
    expect(view.transactions.map((t) => t.id)).toEqual(["newer", "older"]);
  });

  it("renders every LedgerEventKind distinctly rather than collapsing to one shape", () => {
    const kinds = ["debit", "credit", "due", "mandate_created", "mandate_cancelled", "price_change", "refund", "salary", "advance"];
    const nodes = kinds.map((kind, index) =>
      ledgerEventNode({
        id: `ledger-${kind}`,
        fields: { kind, amount: 10, currency: "INR", occurred_at: `2026-08-0${index + 1}T00:00:00Z`, counterparty_raw: "X" },
      }),
    );
    const view = buildLedgerView(nodes, []);
    expect(view.transactions.map((t) => t.kind).sort()).toEqual([...kinds].sort());
  });

  it("skips a malformed LEDGER_EVENT node rather than throwing or fabricating fields", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const view = buildLedgerView(
      [ledgerEventNode({ id: "broken", fields: { kind: "not-a-real-kind", amount: 10, currency: "INR", occurred_at: "2026-08-01T00:00:00Z", counterparty_raw: "X" } })],
      [],
    );
    expect(view.transactions).toHaveLength(0);
    expect(consoleSpy).toHaveBeenCalled();
    consoleSpy.mockRestore();
  });

  it("skips a malformed RECURRING_COMMITMENT node rather than throwing", () => {
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    const view = buildLedgerView([commitmentNode({ id: "broken", fields: { label: "x", counterparty: "y", amount: 1, cadence: "monthly", status: "unknown-status", price_history: [], last_used_at: null } })], []);
    expect(view.commitments).toHaveLength(0);
    consoleSpy.mockRestore();
  });

  it("filters out non-array/malformed price_history entries defensively", () => {
    const view = buildLedgerView(
      [commitmentNode({ id: "c1", fields: { label: "x", counterparty: "y", amount: 1, cadence: "monthly", status: "active", price_history: [["2026-01-01T00:00:00Z", 100], "not-a-tuple", [1, 2]], last_used_at: null } })],
      [],
    );
    expect(view.commitments[0].priceHistory).toEqual([["2026-01-01T00:00:00Z", 100]]);
  });
});

describe("filterTransactions", () => {
  const rows: LedgerTransactionRow[] = [
    {
      id: "t-debit",
      kind: "debit",
      amount: 100,
      currency: "INR",
      counterpartyRaw: "A",
      occurredAt: "2026-08-01T00:00:00Z",
      derivation: "extracted",
      confidence: 0.9,
      sourceDocumentId: null,
      region: null,
      commitmentId: "commitment-1",
    },
    {
      id: "t-advance",
      kind: "advance",
      amount: 2000,
      currency: "INR",
      counterpartyRaw: "B",
      occurredAt: "2026-08-02T00:00:00Z",
      derivation: "extracted",
      confidence: 0.8,
      sourceDocumentId: null,
      region: null,
      commitmentId: null,
    },
  ];

  it("applies no filter when both dimensions are null", () => {
    expect(filterTransactions(rows, { kinds: null, commitmentId: null })).toHaveLength(2);
  });

  it("filters by kind", () => {
    const result = filterTransactions(rows, { kinds: ["advance"], commitmentId: null });
    expect(result.map((r) => r.id)).toEqual(["t-advance"]);
  });

  it("filters by exact commitment id", () => {
    const result = filterTransactions(rows, { kinds: null, commitmentId: "commitment-1" });
    expect(result.map((r) => r.id)).toEqual(["t-debit"]);
  });

  it("filters to unlinked transactions via the UNLINKED_COMMITMENT_FILTER sentinel", () => {
    const result = filterTransactions(rows, { kinds: null, commitmentId: UNLINKED_COMMITMENT_FILTER });
    expect(result.map((r) => r.id)).toEqual(["t-advance"]);
  });

  it("combines both filter dimensions", () => {
    const result = filterTransactions(rows, { kinds: ["debit"], commitmentId: "commitment-1" });
    expect(result.map((r) => r.id)).toEqual(["t-debit"]);
  });
});
