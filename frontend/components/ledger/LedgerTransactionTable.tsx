"use client";

import type { BadgeVariant } from "@/components/design-system/Badge";
import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import { formatDateTime } from "@/lib/approvals";
import {
  LEDGER_EVENT_KINDS,
  LEDGER_EVENT_KIND_LABELS,
  UNLINKED_COMMITMENT_FILTER,
  type LedgerCommitmentRow,
  type LedgerEventKind,
  type LedgerTransactionRow,
} from "@/lib/ledger-transactions";
import styles from "./LedgerTransactionTable.module.css";

export interface LedgerTransactionTableProps {
  readonly transactions: readonly LedgerTransactionRow[];
  readonly allTransactionCount: number;
  readonly commitments: readonly LedgerCommitmentRow[];
  readonly kindFilter: readonly LedgerEventKind[] | null;
  readonly onKindFilterChange: (next: readonly LedgerEventKind[] | null) => void;
  readonly commitmentFilter: string | null;
  readonly onCommitmentFilterChange: (next: string | null) => void;
  readonly onProposeMandateCancel: (commitment: LedgerCommitmentRow) => void;
  /** Commitment ids that already have a mandate-cancel approval item
   * proposed — disables the button and shows a status note instead of
   * offering it again. */
  readonly proposedMandateCancelIds: ReadonlySet<string>;
}

const KIND_BADGE_VARIANT: Record<LedgerEventKind, BadgeVariant> = {
  debit: "neutral",
  credit: "success",
  due: "warning",
  mandate_created: "info",
  mandate_cancelled: "danger",
  price_change: "warning",
  refund: "success",
  salary: "royal",
  advance: "brass",
};

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 }).format(amount);
}

function toggleKind(current: readonly LedgerEventKind[] | null, kind: LedgerEventKind): readonly LedgerEventKind[] | null {
  const set = new Set(current ?? LEDGER_EVENT_KINDS);
  if (set.has(kind)) set.delete(kind);
  else set.add(kind);
  if (set.size === LEDGER_EVENT_KINDS.length) return null;
  return LEDGER_EVENT_KINDS.filter((k) => set.has(k));
}

/**
 * The Ledger view's real transaction list (PHASES.md Phase 7, E4 work item)
 * — every row comes from a live `LEDGER_EVENT` / `RECURRING_COMMITMENT`
 * graph node (`transactions`/`commitments` props, built by
 * `lib/ledger-transactions.ts` from a real `/graph/snapshot` fetch), never
 * fixture data. Filterable by kind (multi-select chips) and by commitment
 * (a single-select including an explicit "not linked to any series"
 * bucket), and every `LedgerEventKind` renders with its own distinct badge
 * colour so ADVANCE and SALARY never read as "just another debit."
 *
 * Each active commitment row also carries the "propose cancelling this
 * mandate" action — spec's "live silent-mandate kill" demo beat — which
 * this component only ever *proposes*; the caller (`LedgerExplorer`) is
 * what routes the proposal through the real Approval Gate.
 */
export function LedgerTransactionTable({
  transactions,
  allTransactionCount,
  commitments,
  kindFilter,
  onKindFilterChange,
  commitmentFilter,
  onCommitmentFilterChange,
  onProposeMandateCancel,
  proposedMandateCancelIds,
}: LedgerTransactionTableProps) {
  const commitmentLabelById = new Map(commitments.map((c) => [c.id, c.label] as const));

  return (
    <div className={styles.wrapper}>
      <div className={styles.filters} aria-label="Transaction filters">
        <fieldset className={styles.filterGroup}>
          <legend className={styles.filterLabel}>Kind</legend>
          <div className={styles.chipRow}>
            {LEDGER_EVENT_KINDS.map((kind) => {
              const active = kindFilter === null || kindFilter.includes(kind);
              return (
                <button
                  key={kind}
                  type="button"
                  aria-pressed={active}
                  className={[styles.chip, active && styles.chipActive].filter(Boolean).join(" ")}
                  onClick={() => onKindFilterChange(toggleKind(kindFilter, kind))}
                >
                  {LEDGER_EVENT_KIND_LABELS[kind]}
                </button>
              );
            })}
          </div>
        </fieldset>

        <div className={styles.filterGroup}>
          <label htmlFor="ledger-commitment-filter" className={styles.filterLabel}>
            Commitment
          </label>
          <select
            id="ledger-commitment-filter"
            className={styles.select}
            value={commitmentFilter ?? ""}
            onChange={(event) => onCommitmentFilterChange(event.target.value.length > 0 ? event.target.value : null)}
          >
            <option value="">Every transaction</option>
            <option value={UNLINKED_COMMITMENT_FILTER}>Not linked to a series</option>
            {commitments.map((commitment) => (
              <option key={commitment.id} value={commitment.id}>
                {commitment.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <p className={styles.summary} role="status" aria-live="polite">
        Showing {transactions.length} of {allTransactionCount} transactions.
      </p>

      {transactions.length === 0 ? (
        <p className={styles.emptyState}>No transactions match the current filters.</p>
      ) : (
        <ul className={styles.transactionList}>
          {transactions.map((transaction) => (
            <li key={transaction.id} className={styles.transactionRow}>
              <Badge variant={KIND_BADGE_VARIANT[transaction.kind]}>{LEDGER_EVENT_KIND_LABELS[transaction.kind]}</Badge>
              <span className={styles.amount}>{formatCurrency(transaction.amount, transaction.currency)}</span>
              <span className={styles.counterparty}>{transaction.counterpartyRaw}</span>
              <span className={styles.date}>{formatDateTime(transaction.occurredAt)}</span>
              {transaction.commitmentId && (
                <span className={styles.commitmentTag}>
                  {commitmentLabelById.get(transaction.commitmentId) ?? transaction.commitmentId}
                </span>
              )}
              {transaction.derivation && (
                <DerivationBadge derivation={transaction.derivation} confidence={transaction.confidence ?? undefined} />
              )}
            </li>
          ))}
        </ul>
      )}

      <div className={styles.commitmentsSection}>
        <h3 className={styles.commitmentsHeading}>Recurring commitments ({commitments.length})</h3>
        {commitments.length === 0 ? (
          <p className={styles.emptyState}>No recurring commitments in the graph yet.</p>
        ) : (
          <ul className={styles.commitmentList}>
            {commitments.map((commitment) => {
              const alreadyProposed = proposedMandateCancelIds.has(commitment.id);
              const cancellable = commitment.status === "active";
              return (
                <li key={commitment.id} className={styles.commitmentRow}>
                  <div className={styles.commitmentInfo}>
                    <span className={styles.commitmentLabel}>{commitment.label}</span>
                    <span className={styles.commitmentDetail}>
                      {commitment.counterparty}, {formatCurrency(commitment.amount, "INR")}/{commitment.cadence}, {" "}
                      <Badge variant={commitment.status === "active" ? "success" : "neutral"}>{commitment.status}</Badge>
                    </span>
                    <span className={styles.commitmentDetail}>
                      {commitment.lastUsedAt
                        ? `Last used ${formatDateTime(commitment.lastUsedAt)}`
                        : "No recorded usage on file"}
                    </span>
                  </div>
                  {cancellable &&
                    (alreadyProposed ? (
                      <p className={styles.proposedNote} role="status">
                        Cancellation proposed, see the approval gate below.
                      </p>
                    ) : (
                      <Button variant="danger" onClick={() => onProposeMandateCancel(commitment)}>
                        Propose cancelling this mandate
                      </Button>
                    ))}
                </li>
              );
            })}
          </ul>
        )}
      </div>
    </div>
  );
}
