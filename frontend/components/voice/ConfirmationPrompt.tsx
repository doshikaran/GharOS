import Link from "next/link";
import { Card } from "@/components/design-system/Card";
import type { ConfirmationPromptEvent } from "@/lib/voice-types";
import styles from "./ConfirmationPrompt.module.css";

/**
 * Client-side heuristic for "this read-back concerns money" — a rupee
 * amount pattern in the server's own read-back text. **Disclosed as a
 * heuristic, not treated as authoritative**: the ADR-020 wire contract's
 * `confirmation_prompt` frame carries only `{text, requires_affirmative,
 * turn_id}` — no `risk_tier` field — so this component cannot know for
 * certain a given prompt is gating an R3 action. Where this pattern
 * matches, the stronger "finalise on the visual surface" messaging is
 * shown; where it doesn't, the general explicit-affirmative rule below
 * still always applies regardless of tier.
 */
const RUPEE_AMOUNT_PATTERN = /₹\s?[\d,]+/;

export interface ConfirmationPromptProps {
  readonly prompt: ConfirmationPromptEvent;
  /** From `useApprovalQueueCount` — the live count already shown on the
   * shell's own Approvals nav badge (ADR-018), reused rather than a
   * second, divergent count. */
  readonly pendingApprovalCount: number;
}

/**
 * The safety-critical read-back UI (spec §14.6). **Deliberately renders no
 * clickable "Yes"/"No" button.** The ADR-020 wire contract's only
 * client→server channel is binary mic audio — there is no defined
 * message for "the household member clicked Confirm." A button here
 * would be a UI action with no real backend effect, which the standing
 * "no fabricated success" invariant (gharos-standards) forbids. The real
 * affirmative must be **spoken** — held mic button or hands-free mode,
 * same `MicControl` already on screen — and is recognised server-side by
 * A68, never inferred here from a click, a timeout, or silence.
 *
 * Rendered in an `aria-live="assertive"` region (a step up from the
 * transcript's own `"polite"` log) since a missed confirmation prompt is
 * the single highest-cost thing this surface could fail to announce.
 */
export function ConfirmationPrompt({ prompt, pendingApprovalCount }: ConfirmationPromptProps) {
  const looksLikeMoney = RUPEE_AMOUNT_PATTERN.test(prompt.text);

  return (
    <div role="alert" aria-live="assertive" className={styles.liveRegion}>
      <Card title="Please confirm" className={styles.card}>
        <p className={styles.readback}>{prompt.text}</p>
        <p className={styles.instruction}>
          Say a clear <strong>“yes”</strong> to confirm, or <strong>“no”</strong> to cancel. Silence or an unclear
          reply is <strong>not</strong> treated as approval — you will be asked again, as many times as needed.
        </p>
        {looksLikeMoney && (
          <p className={styles.moneyNotice}>
            This involves a payment. Even after you say yes, GharOS will not move any money from your voice
            confirmation alone —{" "}
            <Link href="/approvals" className={styles.approvalsLink}>
              confirm it in your Approvals tab
            </Link>{" "}
            to finish it
            {pendingApprovalCount > 0
              ? ` (you have ${pendingApprovalCount} item${pendingApprovalCount === 1 ? "" : "s"} waiting there now)`
              : ""}
            .
          </p>
        )}
      </Card>
    </div>
  );
}
