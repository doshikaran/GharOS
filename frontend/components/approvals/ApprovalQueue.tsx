import { isResolved, needsApproval, type ApprovalQueueItem } from "@/lib/approvals";
import { ApprovalCard } from "./ApprovalCard";
import styles from "./ApprovalQueue.module.css";

export interface ApprovalQueueProps {
  items: readonly ApprovalQueueItem[];
  onApprove?: (id: string) => void;
  onReject?: (id: string) => void;
  /** Injectable clock for deterministic tests; defaults to the real time. */
  now?: Date;
}

/**
 * The approve/reject queue. Deliberately excludes every R4 item and every
 * expired item — both belong on `EscalationSurface` instead, which reads
 * as presenting options for a human decision rather than another
 * approve/reject row (this phase's brief). Also renders a read-only
 * history of already-resolved items, so the tiering system stays legible
 * end to end rather than items vanishing the moment they're decided.
 */
export function ApprovalQueue({ items, onApprove, onReject, now }: ApprovalQueueProps) {
  const clock = now ?? new Date();
  const pending = items.filter((item) => needsApproval(item, clock));
  const resolved = items.filter((item) => isResolved(item, clock));

  return (
    <div className={styles.queue}>
      <section aria-label="Needs your decision">
        <h3 className={styles.sectionHeading}>Needs your decision ({pending.length})</h3>
        {pending.length === 0 ? (
          <p className={styles.emptyState}>Nothing is awaiting approval right now.</p>
        ) : (
          <div className={styles.cardList}>
            {pending.map((item) => (
              <ApprovalCard key={item.id} item={item} onApprove={onApprove} onReject={onReject} now={clock} />
            ))}
          </div>
        )}
      </section>

      <section aria-label="Resolved">
        <h3 className={styles.sectionHeading}>Resolved ({resolved.length})</h3>
        {resolved.length === 0 ? (
          <p className={styles.emptyState}>No resolved requests yet.</p>
        ) : (
          <div className={styles.cardList}>
            {resolved.map((item) => (
              <ApprovalCard key={item.id} item={item} now={clock} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
