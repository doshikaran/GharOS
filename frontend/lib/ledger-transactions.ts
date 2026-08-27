/**
 * Turns the live `/graph/snapshot` node/edge set into the Household Ledger
 * view's transaction list and recurring-commitment list (PHASES.md Phase 7,
 * E4 work item — "Ledger view... a real transaction list from live
 * LEDGER_EVENT / RECURRING_COMMITMENT graph data").
 *
 * **This is the one part of this phase's ledger UI backed by a real, live
 * endpoint** (`lib/graph-api.ts`'s `fetchGraphSnapshot`), not fixture data —
 * see `lib/ledger.ts`'s module docstring for the rest of this phase's
 * fixture/live split. Every field read out of a `GraphNode.fields` bag
 * below is exactly what `app.graph.serialization.build_node_envelope`
 * writes for a `LedgerEvent` / `RecurringCommitment` node — read that
 * module directly rather than guessed at.
 */

import type { Derivation, GraphEdge, GraphNode } from "./graph-types";

// ---------------------------------------------------------------------------
// LedgerEventKind — `contracts.graph_types.LedgerEventKind`, verbatim values.
// ---------------------------------------------------------------------------

export const LEDGER_EVENT_KINDS = [
  "debit",
  "credit",
  "due",
  "mandate_created",
  "mandate_cancelled",
  "price_change",
  "refund",
  "salary",
  "advance",
] as const;

export type LedgerEventKind = (typeof LEDGER_EVENT_KINDS)[number];

/** Every kind rendered distinctly — spec's own brief calls out ADVANCE and
 * SALARY specifically, since Phase 7's own new payroll work turns on
 * telling those two apart from an ordinary DEBIT at a glance. */
export const LEDGER_EVENT_KIND_LABELS: Record<LedgerEventKind, string> = {
  debit: "Debit",
  credit: "Credit",
  due: "Due",
  mandate_created: "Mandate created",
  mandate_cancelled: "Mandate cancelled",
  price_change: "Price change",
  refund: "Refund",
  salary: "Salary",
  advance: "Advance",
};

function isLedgerEventKind(value: unknown): value is LedgerEventKind {
  return typeof value === "string" && (LEDGER_EVENT_KINDS as readonly string[]).includes(value);
}

// ---------------------------------------------------------------------------
// Row shapes — the real per-type fields, camelCased, plus the envelope's
// shared provenance fields the ledger view also renders (derivation,
// confidence, source document).
// ---------------------------------------------------------------------------

export interface LedgerTransactionRow {
  readonly id: string;
  readonly kind: LedgerEventKind;
  readonly amount: number;
  readonly currency: string;
  readonly counterpartyRaw: string;
  /** ISO 8601 — mirrors `LedgerEvent.occurred_at`. */
  readonly occurredAt: string;
  readonly derivation: Derivation | null;
  readonly confidence: number | null;
  readonly sourceDocumentId: string | null;
  readonly region: string | null;
  /** The RECURRING_COMMITMENT this event belongs to, resolved from a real
   * `belongs_to` graph edge (spec §5.3: `LEDGER_EVENT -> RECURRING_COMMITMENT`,
   * "series membership") — `null` when this event belongs to no known
   * series, a real and common case (e.g. a one-off grocery debit). */
  readonly commitmentId: string | null;
}

export interface LedgerCommitmentRow {
  readonly id: string;
  readonly label: string;
  readonly counterparty: string;
  readonly amount: number;
  readonly cadence: string;
  /** `[occurredAtIso, price][]`, oldest first — mirrors
   * `RecurringCommitment.price_history`'s tuple-of-tuples shape once JSON-safe. */
  readonly priceHistory: readonly (readonly [string, number])[];
  readonly lastUsedAt: string | null;
  readonly status: "active" | "paused" | "cancelled";
  readonly derivation: Derivation | null;
  readonly confidence: number | null;
}

export interface LedgerView {
  readonly transactions: readonly LedgerTransactionRow[];
  readonly commitments: readonly LedgerCommitmentRow[];
}

const BELONGS_TO_EDGE_TYPE = "belongs_to";

function parseTransaction(
  node: GraphNode,
  commitmentByEventId: ReadonlyMap<string, string>,
): LedgerTransactionRow | null {
  const kind = node.fields["kind"];
  const amount = node.fields["amount"];
  const currency = node.fields["currency"];
  const occurredAt = node.fields["occurred_at"];
  const counterpartyRaw = node.fields["counterparty_raw"];

  if (
    !isLedgerEventKind(kind) ||
    typeof amount !== "number" ||
    typeof currency !== "string" ||
    typeof occurredAt !== "string" ||
    typeof counterpartyRaw !== "string"
  ) {
    console.error("ledger-transactions: skipping malformed LEDGER_EVENT node", node.id);
    return null;
  }

  return {
    id: node.id,
    kind,
    amount,
    currency,
    counterpartyRaw,
    occurredAt,
    derivation: node.derivation,
    confidence: node.confidence,
    sourceDocumentId: node.source_document_id,
    region: node.region,
    commitmentId: commitmentByEventId.get(node.id) ?? null,
  };
}

function isPriceHistoryEntry(value: unknown): value is readonly [string, number] {
  return Array.isArray(value) && value.length === 2 && typeof value[0] === "string" && typeof value[1] === "number";
}

function parseCommitment(node: GraphNode): LedgerCommitmentRow | null {
  const label = node.fields["label"];
  const counterparty = node.fields["counterparty"];
  const amount = node.fields["amount"];
  const cadence = node.fields["cadence"];
  const status = node.fields["status"];
  const priceHistoryRaw = node.fields["price_history"];
  const lastUsedAt = node.fields["last_used_at"];

  if (
    typeof label !== "string" ||
    typeof counterparty !== "string" ||
    typeof amount !== "number" ||
    typeof cadence !== "string" ||
    (status !== "active" && status !== "paused" && status !== "cancelled")
  ) {
    console.error("ledger-transactions: skipping malformed RECURRING_COMMITMENT node", node.id);
    return null;
  }

  const priceHistory = Array.isArray(priceHistoryRaw) ? priceHistoryRaw.filter(isPriceHistoryEntry) : [];

  return {
    id: node.id,
    label,
    counterparty,
    amount,
    cadence,
    priceHistory,
    lastUsedAt: typeof lastUsedAt === "string" ? lastUsedAt : null,
    status,
    derivation: node.derivation,
    confidence: node.confidence,
  };
}

/**
 * Builds the ledger view's real data from a live `GraphSnapshot`'s nodes
 * and edges — every `LEDGER_EVENT` and `RECURRING_COMMITMENT` node present,
 * transactions sorted newest-first, each transaction resolved to its
 * commitment (if any) via the real `belongs_to` edge.
 */
export function buildLedgerView(nodes: readonly GraphNode[], edges: readonly GraphEdge[]): LedgerView {
  const commitmentByEventId = new Map<string, string>();
  for (const edge of edges) {
    if (edge.type === BELONGS_TO_EDGE_TYPE) {
      commitmentByEventId.set(edge.from_id, edge.to_id);
    }
  }

  const transactions: LedgerTransactionRow[] = [];
  const commitments: LedgerCommitmentRow[] = [];

  for (const node of nodes) {
    if (node.type === "LEDGER_EVENT") {
      const row = parseTransaction(node, commitmentByEventId);
      if (row) transactions.push(row);
    } else if (node.type === "RECURRING_COMMITMENT") {
      const row = parseCommitment(node);
      if (row) commitments.push(row);
    }
  }

  transactions.sort((a, b) => new Date(b.occurredAt).getTime() - new Date(a.occurredAt).getTime());

  return { transactions, commitments };
}

// ---------------------------------------------------------------------------
// Client-side filtering — by kind (multi-select) and by commitment
// (single-select, plus an explicit "unlinked" bucket).
// ---------------------------------------------------------------------------

/** Sentinel `commitmentId` value matching only transactions with no known
 * series (`commitmentId === null`) — distinct from `null` itself, which
 * means "no commitment filter engaged at all" (show every transaction). */
export const UNLINKED_COMMITMENT_FILTER = "unlinked" as const;

export interface LedgerTransactionFilters {
  /** `null` means "no kind filter" (show every kind). */
  readonly kinds: readonly LedgerEventKind[] | null;
  /** `null` means "no commitment filter". `UNLINKED_COMMITMENT_FILTER`
   * matches only transactions with no resolved commitment. Any other
   * string matches that exact commitment id. */
  readonly commitmentId: string | null;
}

export const EMPTY_LEDGER_TRANSACTION_FILTERS: LedgerTransactionFilters = {
  kinds: null,
  commitmentId: null,
};

export function filterTransactions(
  rows: readonly LedgerTransactionRow[],
  filters: LedgerTransactionFilters,
): readonly LedgerTransactionRow[] {
  return rows.filter((row) => {
    if (filters.kinds !== null && !filters.kinds.includes(row.kind)) return false;
    if (filters.commitmentId !== null) {
      if (filters.commitmentId === UNLINKED_COMMITMENT_FILTER) {
        if (row.commitmentId !== null) return false;
      } else if (row.commitmentId !== filters.commitmentId) {
        return false;
      }
    }
    return true;
  });
}
