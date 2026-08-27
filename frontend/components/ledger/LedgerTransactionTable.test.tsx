import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import type { LedgerCommitmentRow, LedgerTransactionRow } from "@/lib/ledger-transactions";
import { LedgerTransactionTable } from "./LedgerTransactionTable";

const transactions: LedgerTransactionRow[] = [
  {
    id: "ledger-maintenance-debit",
    kind: "debit",
    amount: 2500,
    currency: "INR",
    counterpartyRaw: "SUNRISE SOCIETY MAINT",
    occurredAt: "2026-08-22T06:00:00Z",
    derivation: "extracted",
    confidence: 0.9,
    sourceDocumentId: "doc-society-notice",
    region: "payment-confirmation",
    commitmentId: "commitment-society-maintenance",
  },
  {
    id: "ledger-maya-advance",
    kind: "advance",
    amount: 2000,
    currency: "INR",
    counterpartyRaw: "MAYA BAI",
    occurredAt: "2026-08-12T00:00:00Z",
    derivation: "extracted",
    confidence: 0.8,
    sourceDocumentId: "doc-attendance-register",
    region: "margin-note",
    commitmentId: null,
  },
];

const commitments: LedgerCommitmentRow[] = [
  {
    id: "commitment-society-maintenance",
    label: "Sunrise Society maintenance",
    counterparty: "Sunrise Apartments Society",
    amount: 2500,
    cadence: "monthly",
    priceHistory: [
      ["2025-08-22T09:00:00Z", 2300],
      ["2026-07-23T09:00:00Z", 2500],
    ],
    lastUsedAt: "2026-07-23T09:00:00Z",
    status: "active",
    derivation: "extracted",
    confidence: 0.9,
  },
];

function noop() {}

describe("LedgerTransactionTable", () => {
  it("renders every real transaction with its kind, amount, counterparty and date", () => {
    render(
      <LedgerTransactionTable
        transactions={transactions}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={null}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set()}
      />,
    );
    expect(screen.getByText("SUNRISE SOCIETY MAINT")).toBeInTheDocument();
    expect(screen.getByText("MAYA BAI")).toBeInTheDocument();
    // "Advance"/"Debit" also appear as filter-chip button labels — scope to
    // the badge (a <span>) to assert the transaction row itself renders them.
    expect(screen.getByText("Advance", { selector: "span" })).toBeInTheDocument();
    expect(screen.getByText("Debit", { selector: "span" })).toBeInTheDocument();
  });

  it("shows a real N-of-M summary reflecting the already-filtered set passed in", () => {
    render(
      <LedgerTransactionTable
        transactions={[transactions[0]]}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={["debit"]}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set()}
      />,
    );
    expect(screen.getByRole("status")).toHaveTextContent("Showing 1 of 2 transactions.");
  });

  it("toggles a kind filter chip via onKindFilterChange", () => {
    const onKindFilterChange = vi.fn();
    render(
      <LedgerTransactionTable
        transactions={transactions}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={null}
        onKindFilterChange={onKindFilterChange}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Advance" }));
    expect(onKindFilterChange).toHaveBeenCalledTimes(1);
    const nextFilter = onKindFilterChange.mock.calls[0][0];
    expect(nextFilter).not.toContain("advance");
  });

  it("changes the commitment filter via the select, including the 'not linked to a series' bucket", () => {
    const onCommitmentFilterChange = vi.fn();
    render(
      <LedgerTransactionTable
        transactions={transactions}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={null}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={onCommitmentFilterChange}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set()}
      />,
    );
    fireEvent.change(screen.getByLabelText("Commitment"), { target: { value: "unlinked" } });
    expect(onCommitmentFilterChange).toHaveBeenCalledWith("unlinked");
  });

  it("shows an empty state when no transactions match the current filters", () => {
    render(
      <LedgerTransactionTable
        transactions={[]}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={["salary"]}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set()}
      />,
    );
    expect(screen.getByText("No transactions match the current filters.")).toBeInTheDocument();
  });

  it("offers 'propose cancelling this mandate' on an active commitment, invoking the callback with the real commitment row", () => {
    const onProposeMandateCancel = vi.fn();
    render(
      <LedgerTransactionTable
        transactions={transactions}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={null}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={onProposeMandateCancel}
        proposedMandateCancelIds={new Set()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "Propose cancelling this mandate" }));
    expect(onProposeMandateCancel).toHaveBeenCalledWith(commitments[0]);
  });

  it("shows a status note instead of the button once a mandate cancellation has already been proposed", () => {
    render(
      <LedgerTransactionTable
        transactions={transactions}
        allTransactionCount={transactions.length}
        commitments={commitments}
        kindFilter={null}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set(["commitment-society-maintenance"])}
      />,
    );
    expect(screen.queryByRole("button", { name: "Propose cancelling this mandate" })).not.toBeInTheDocument();
    expect(screen.getByText(/Cancellation proposed/)).toBeInTheDocument();
  });

  it("never offers cancellation on a non-active commitment", () => {
    const cancelledCommitment: LedgerCommitmentRow = { ...commitments[0], id: "commitment-cancelled", status: "cancelled" };
    render(
      <LedgerTransactionTable
        transactions={transactions}
        allTransactionCount={transactions.length}
        commitments={[cancelledCommitment]}
        kindFilter={null}
        onKindFilterChange={noop}
        commitmentFilter={null}
        onCommitmentFilterChange={noop}
        onProposeMandateCancel={noop}
        proposedMandateCancelIds={new Set()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Propose cancelling this mandate" })).not.toBeInTheDocument();
  });
});
