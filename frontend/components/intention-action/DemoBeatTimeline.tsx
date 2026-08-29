import { ArrowDown, Clock, Mail, Search, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import type { ModalitySwitchResult, StaleObligationDetection, WindowFindingResult } from "@/lib/intention-action";
import styles from "./DemoBeatTimeline.module.css";

export interface DemoBeatTimelineProps {
  readonly stale: StaleObligationDetection;
  readonly attemptCount: number;
  readonly modalitySwitch: ModalitySwitchResult;
  readonly windowResult: WindowFindingResult;
  readonly resolutionSeconds: number;
}

function formatWindow(windowRange: readonly [string, string]): string {
  const start = new Date(windowRange[0]);
  return start.toLocaleDateString("en-IN", {
    weekday: "long",
    day: "numeric",
    month: "short",
    hour: "numeric",
    minute: "2-digit",
    timeZone: "UTC",
  });
}

/**
 * spec §9.6's demo beat, made concrete: "a task untouched for four months
 * completes in 30 seconds because the agent removed the actual blocker" —
 * a real before (stale, untouched, {attemptCount} failed attempts) / after
 * (diagnosed → unblocked → scheduled) for one real obligation, consistent
 * with the rest of this household's data (this phase's brief item 5).
 */
export function DemoBeatTimeline({ stale, attemptCount, modalitySwitch, windowResult, resolutionSeconds }: DemoBeatTimelineProps) {
  return (
    <div className={styles.wrapper}>
      <Card className={styles.beforeCard} title="Before">
        <div className={styles.beforeBody}>
          <Clock size={28} strokeWidth={1.75} aria-hidden="true" className={styles.beforeIcon} />
          <p className={styles.staleFigure} data-testid="stale-days">
            {stale.daysStale} days untouched
          </p>
          <p className={styles.staleReason}>{stale.reason}</p>
          <Badge variant="danger">{attemptCount} failed unblocking attempts</Badge>
        </div>
      </Card>

      <div className={styles.arrow} aria-hidden="true">
        <ArrowDown size={24} strokeWidth={2} />
      </div>

      <Card className={styles.afterCard} title="After">
        <ol className={styles.afterSteps}>
          <li className={styles.afterStep}>
            <Search size={18} strokeWidth={2} aria-hidden="true" />
            <span>The real blocker, correctly diagnosed at last: aversion, not information.</span>
          </li>
          <li className={styles.afterStep}>
            <Mail size={18} strokeWidth={2} aria-hidden="true" />
            <span>
              Unblocked, {modalitySwitch.fromModality} switched to {modalitySwitch.toModality}, message pre-drafted
              and sent.
            </span>
          </li>
          <li className={styles.afterStep}>
            <ShieldCheck size={18} strokeWidth={2} aria-hidden="true" />
            <span>Scheduled, {windowResult.bestWindow ? formatWindow(windowResult.bestWindow) : "no window found"}.</span>
          </li>
        </ol>
        <p className={styles.resolutionFigure} data-testid="resolution-seconds">
          Resolved in {resolutionSeconds} seconds once the real blocker was gone.
        </p>
      </Card>
    </div>
  );
}
