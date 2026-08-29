import { isEscalation, isExpired, type ApprovalQueueItem } from "@/lib/approvals";
import { EscalationCard } from "./EscalationCard";
import styles from "./EscalationSurface.module.css";

export interface EscalationSurfaceProps {
  items: readonly ApprovalQueueItem[];
  discussedIds?: ReadonlySet<string>;
  onToggleDiscussed?: (id: string, discussed: boolean) => void;
  /** Injectable clock for deterministic tests; defaults to the real time. */
  now?: Date;
}

/**
 * The escalation surface (spec §7.7, §18.1) — genuinely different
 * treatment from the approve/reject queue, per this phase's brief: no
 * Approve/Reject button appears anywhere on this surface. It groups the
 * two distinct reasons an item escalates so a reader can tell them apart
 * at a glance: R4 "escalate only" Council briefs (never auto-executed, by
 * policy, regardless of confidence) and requests whose approval window
 * expired without a human decision (never silently treated as approved).
 */
export function EscalationSurface({ items, discussedIds, onToggleDiscussed, now }: EscalationSurfaceProps) {
  const clock = now ?? new Date();
  const escalated = items.filter((item) => isEscalation(item, clock));
  const councilBriefs = escalated.filter((item) => item.riskTier === "R4");
  const expiredRequests = escalated.filter((item) => item.riskTier !== "R4" && isExpired(item, clock));

  if (escalated.length === 0) {
    return (
      <div className={styles.surface}>
        <p className={styles.emptyState}>Nothing is escalated right now.</p>
      </div>
    );
  }

  return (
    <div className={styles.surface}>
      {councilBriefs.length > 0 && (
        <section aria-label="Council briefs">
          <h3 className={styles.sectionHeading}>Council briefs, awaiting a household decision</h3>
          <p className={styles.sectionIntro}>
            These are never auto-executed. The Council does not resolve them, each card below is the brief
            it produced; a household member decides.
          </p>
          <div className={styles.cardList}>
            {councilBriefs.map((item) => (
              <EscalationCard
                key={item.id}
                item={item}
                now={clock}
                discussed={discussedIds?.has(item.id) ?? false}
                onToggleDiscussed={onToggleDiscussed}
              />
            ))}
          </div>
        </section>
      )}

      {expiredRequests.length > 0 && (
        <section aria-label="Expired approvals">
          <h3 className={styles.sectionHeading}>Escalated, approval window expired</h3>
          <p className={styles.sectionIntro}>
            No decision arrived before the window closed. Expiry escalated these, it did not approve them.
          </p>
          <div className={styles.cardList}>
            {expiredRequests.map((item) => (
              <EscalationCard
                key={item.id}
                item={item}
                now={clock}
                discussed={discussedIds?.has(item.id) ?? false}
                onToggleDiscussed={onToggleDiscussed}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
