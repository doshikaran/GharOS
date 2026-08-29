import { Badge, type BadgeVariant } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { ConfidenceMeter } from "@/components/approvals/ConfidenceMeter";
import { formatDateTime } from "@/lib/approvals";
import type { LeakageCase, LeakageVerdict } from "@/lib/ledger";
import styles from "./LeakageRecoverySurface.module.css";

const VERDICT_LABEL: Record<LeakageVerdict, string> = {
  leakage: "Leakage",
  worth_keeping: "Worth keeping",
  ambiguous: "Ambiguous, flagged for a human",
};

const VERDICT_VARIANT: Record<LeakageVerdict, BadgeVariant> = {
  leakage: "danger",
  worth_keeping: "success",
  ambiguous: "warning",
};

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 }).format(amount);
}

export interface LeakageCaseCardProps {
  readonly leakageCase: LeakageCase;
}

/**
 * One A29 verdict on one recurring commitment, with its real usage
 * evidence and — when one exists — the A30 `RecoveryDraft` it produced.
 * The draft is rendered strictly read-only: there is no send affordance
 * anywhere here, matching `RecoveryDraft`'s own backend design (no
 * `sent_at` field exists on the real type at all — sending is out of
 * scope for every agent in this package).
 */
export function LeakageCaseCard({ leakageCase }: LeakageCaseCardProps) {
  const { request, finding, recoveryDraft } = leakageCase;

  return (
    <Card
      className={styles.card}
      title={
        <span className={styles.titleRow}>
          <span>
            {request.label}, {request.counterparty}
          </span>
          <Badge variant={VERDICT_VARIANT[finding.verdict]}>{VERDICT_LABEL[finding.verdict]}</Badge>
        </span>
      }
    >
      <div className={styles.body}>
        <p className={styles.amountLine}>
          {formatCurrency(request.amount, "INR")} / {request.cadence}
        </p>

        <section aria-label="Reasoning">
          <h4 className={styles.sectionLabel}>Reasoning</h4>
          <p className={styles.reasoning}>{finding.reasoning}</p>
        </section>

        <section aria-label="Usage evidence">
          <h4 className={styles.sectionLabel}>Usage evidence</h4>
          <ul className={styles.evidenceList}>
            <li>
              {request.lastUsedAt
                ? `Last used ${formatDateTime(request.lastUsedAt)}${
                    finding.daysSinceLastUsed !== null ? ` (${finding.daysSinceLastUsed} days ago)` : ""
                  }`
                : "No recorded usage on file"}
            </li>
            {finding.priceChangePct !== null && (
              <li>Price changed {finding.priceChangePct.toFixed(1)}% across the price history on file.</li>
            )}
            {Object.entries(finding.evidence).map(([key, value]) => (
              <li key={key}>
                {key.replaceAll("_", " ")}: {value}
              </li>
            ))}
            <li className={styles.householdPriority}>Household priority on file: &ldquo;{request.householdPriorities}&rdquo;</li>
          </ul>
        </section>

        <section aria-label="Confidence">
          <h4 className={styles.sectionLabel}>Confidence</h4>
          <ConfidenceMeter confidence={finding.confidence} />
        </section>

        {recoveryDraft ? (
          <section aria-label="Drafted claim" className={styles.draftSection}>
            <h4 className={styles.sectionLabel}>Drafted claim, {recoveryDraft.targetVendor}</h4>
            <p className={styles.draftAsk}>{recoveryDraft.ask}</p>
            <blockquote className={styles.draftMessage}>{recoveryDraft.messageText}</blockquote>
            <p className={styles.draftReasoning}>{recoveryDraft.reasoning}</p>
            <p className={styles.readOnlyNote} role="note">
              Read-only, this claim has been drafted only. It is never sent automatically; sending requires a
              separate, explicit action outside this system.
            </p>
          </section>
        ) : (
          <p className={styles.noDraftNote}>No claim drafted for this commitment.</p>
        )}
      </div>
    </Card>
  );
}

export interface LeakageRecoverySurfaceProps {
  readonly cases: readonly LeakageCase[];
}

/**
 * A real, browsable list of every `LeakageFinding` A29 has produced this
 * pass, each optionally paired with its `RecoveryDraft` (PHASES.md Phase 7,
 * E4 work item 5).
 */
export function LeakageRecoverySurface({ cases }: LeakageRecoverySurfaceProps) {
  if (cases.length === 0) {
    return <p className={styles.emptyState}>No leakage findings on file yet.</p>;
  }

  return (
    <div className={styles.surface}>
      {cases.map((leakageCase) => (
        <LeakageCaseCard key={leakageCase.request.commitmentId} leakageCase={leakageCase} />
      ))}
    </div>
  );
}
