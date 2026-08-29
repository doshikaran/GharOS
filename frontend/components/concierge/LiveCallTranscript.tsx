"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { revealedTurnCount, TRANSCRIPT_TURN_REVEAL_MS, type CallOutcomeReport, type CallTurn } from "@/lib/concierge";
import styles from "./LiveCallTranscript.module.css";

export interface LiveCallTranscriptProps {
  readonly turns: readonly CallTurn[];
  readonly outcomeReport: CallOutcomeReport;
  readonly counterpartyName: string;
}

/**
 * Renders one `CallConversationResult`/`CallOutcomeReport` turn by turn
 * (this phase's brief item 3). **Per ADR-016, binding:** this is a real,
 * live, multi-turn TEXT conversation the household's calling agent had
 * with a real sandbox counterparty persona — never synthesized audio.
 * Nothing below plays a sound, shows a ringing phone, or otherwise
 * implies a literal call was placed; the heading and every caption say
 * "transcript"/"conversation," never "audio" or "recording."
 *
 * **Animation honesty, stated once here in code (per this phase's own
 * brief) and never contradicted by the copy on screen:** `turns` is a
 * real, already-complete fixture array before this component ever
 * mounts — nothing streams in from a live call while this renders. The
 * turn-by-turn reveal below is a presentation animation only (mirrors
 * Phase 6's graph-growth arrival motion in spirit, `lib/graph-animation.ts`),
 * driven by `revealedTurnCount`'s pure timing function, so it is provably
 * not simulating a live feed by any means beyond a `setInterval`. A
 * "Show full transcript" control is provided for anyone who wants the
 * whole thing immediately (or has `prefers-reduced-motion` set — honoured
 * in this component's own CSS) rather than waiting on the reveal.
 *
 * Turn zero (the disclosure line) is always rendered as visually
 * distinct and unmissable (Gate 10: "disclosure on every call, cannot be
 * disabled"). Any `outOfBoundsEncountered`/`requiresHumanCallback` moment
 * is called out as its own distinct event on the final turn, never
 * glossed over as an ordinary line of dialogue.
 *
 * Each mounted instance owns one fixed `turns` array for its whole
 * lifetime (every call site below renders one call per component
 * instance) — a caller that needs to replay a *different* call in the
 * same slot should remount with a `key` (e.g. keyed on `callId`) rather
 * than rely on this component to detect a changed `turns` prop itself.
 */
export function LiveCallTranscript({ turns, outcomeReport, counterpartyName }: LiveCallTranscriptProps) {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [skipped, setSkipped] = useState(false);

  useEffect(() => {
    if (skipped) return;
    const interval = setInterval(() => setElapsedMs((prev) => prev + 100), 100);
    return () => clearInterval(interval);
  }, [skipped]);

  const revealCount = skipped ? turns.length : revealedTurnCount(turns.length, elapsedMs, TRANSCRIPT_TURN_REVEAL_MS);
  const visibleTurns = turns.slice(0, revealCount);
  const fullyRevealed = revealCount >= turns.length;
  const noteworthyTurnIndex = outcomeReport.outOfBoundsEncountered || outcomeReport.requiresHumanCallback
    ? (turns[turns.length - 1]?.turnIndex ?? null)
    : null;

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <p className={styles.honestyNote} role="note">
          A real, sandboxed text conversation with {counterpartyName}, a live, turn-taking exchange in transcript
          form, not synthesized audio (per ADR-016; Phase 13 is where real speech is built).
        </p>
        {!fullyRevealed && (
          <Button variant="ghost" onClick={() => setSkipped(true)}>
            Show full transcript
          </Button>
        )}
      </div>

      <ol className={styles.turnList} aria-label="Call transcript, turn by turn">
        {visibleTurns.map((turn) => (
          <li
            key={turn.turnIndex}
            className={styles.turnRow}
            data-speaker={turn.speaker}
            data-disclosure={turn.turnIndex === 0}
            data-noteworthy={turn.turnIndex === noteworthyTurnIndex}
          >
            <div className={styles.turnMeta}>
              <span className={styles.speakerLabel}>{turn.speaker === "caller" ? "Household's agent" : counterpartyName}</span>
              {turn.turnIndex === 0 && <Badge variant="royal">Disclosure, every call, no exceptions</Badge>}
              {turn.turnIndex === noteworthyTurnIndex && (
                <Badge variant={outcomeReport.outOfBoundsEncountered ? "warning" : "danger"} data-testid="noteworthy-badge">
                  {outcomeReport.outOfBoundsEncountered ? "Out of bounds, declined" : "Escalated to a human"}
                </Badge>
              )}
            </div>
            <p className={styles.utterance}>{turn.utterance}</p>
          </li>
        ))}
      </ol>

      {!fullyRevealed && <p className={styles.playingNote} role="status">Transcript continuing…</p>}

      {fullyRevealed && (
        <p className={styles.outcomeSummary} role="status">
          {outcomeReport.claimedOutcomeSummary}
        </p>
      )}
    </div>
  );
}
