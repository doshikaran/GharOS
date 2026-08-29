"use client";

import { useState } from "react";
import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import {
  getConcessionEvidence,
  getEf1Violations,
  getFairAllocationResult,
  getRenegotiationTrigger,
} from "@/lib/fair-allocator";
import { AllocationResult } from "./AllocationResult";
import styles from "./RenegotiationDemo.module.css";

export interface RenegotiationDemoProps {
  readonly taskTitle: (taskId: string) => string;
  readonly personName: (personId: string) => string;
}

function formatDetectedAt(iso: string): string {
  return new Date(iso).toLocaleString("en-IN", { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The demo beat spec §8.7 names directly: "inject 'I just started night
 * shifts' -> live re-allocation" (PHASES.md Phase 8, E4 work item 4). A
 * real button triggers a `RenegotiationTrigger`-shaped event and swaps in
 * a second, distinct `FairAllocationResult` — a genuine before/after, not
 * a re-display of the same numbers (see `lib/fair-allocator.ts`'s own
 * "HAND-CHECKABLE ARITHMETIC" header for the worked derivation of both).
 * When the new allocation involves a real concession, the `ConcessionEvidence`
 * is shown with the exact prior-vs-new bundle cost numbers behind it —
 * never a guess.
 */
export function RenegotiationDemo({ taskTitle, personName }: RenegotiationDemoProps) {
  const [triggered, setTriggered] = useState(false);
  const trigger = getRenegotiationTrigger();
  const concessions = getConcessionEvidence();

  return (
    <div className={styles.wrapper}>
      <Card title="Renegotiation trigger">
        <p className={styles.triggerCopy}>
          Household signal: <strong>&ldquo;{personName(trigger.personId)} just started night shifts.&rdquo;</strong>
        </p>
        <p className={styles.triggerDetail}>{trigger.detail}</p>
        <div className={styles.triggerMeta}>
          <Badge variant="info">Reason: schedule constraint change</Badge>
          <span className={styles.triggerTimestamp}>Detected {formatDetectedAt(trigger.detectedAt)}</span>
        </div>
        {!triggered && (
          <Button variant="brass" className={styles.triggerButton} onClick={() => setTriggered(true)}>
            Inject this trigger, re-run the allocation
          </Button>
        )}
      </Card>

      {triggered && (
        <div className={styles.afterSection}>
          <div className={styles.beforeAfterBanner}>
            <Badge variant="warning">Before → After</Badge>
            <p className={styles.beforeAfterCopy}>
              The allocation below is a genuinely new solve over the same three tasks, using Maya&apos;s revised
              costs, not the earlier result shown again.
            </p>
          </div>

          <AllocationResult
            heading="After: re-allocated following the night-shift trigger"
            result={getFairAllocationResult("after")}
            violations={getEf1Violations("after")}
            taskTitle={taskTitle}
            personName={personName}
          />

          {concessions.length > 0 && (
            <Card title="Concession evidence">
              {concessions.map((concession) => (
                <div key={concession.personId} className={styles.concessionRow}>
                  <p className={styles.concessionHeadline}>
                    <strong>{personName(concession.personId)}</strong> gave ground this cycle.
                  </p>
                  <dl className={styles.concessionFigures}>
                    <div>
                      <dt>Prior bundle, by their own current valuation</dt>
                      <dd>{concession.priorBundleCost.toFixed(1)}</dd>
                    </div>
                    <div>
                      <dt>New bundle, by that same valuation</dt>
                      <dd>{concession.newBundleCost.toFixed(1)}</dd>
                    </div>
                  </dl>
                  <p className={styles.concessionReasoning}>{concession.reasoning}</p>
                </div>
              ))}
            </Card>
          )}
        </div>
      )}
    </div>
  );
}
