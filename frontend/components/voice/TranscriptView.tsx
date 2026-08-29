import type { TranscriptSpan } from "@/lib/voice-types";
import { LanguageSpanChip } from "./LanguageSpanChip";
import styles from "./TranscriptView.module.css";

/**
 * One turn of transcript, aggregated for display. `status` distinguishes
 * an in-progress `transcript_partial` turn (may still change) from a
 * settled `transcript_final` one — this is a UI-only aggregation type;
 * `VoiceSessionPanel` builds this list from the raw
 * `TranscriptPartialEvent`/`TranscriptFinalEvent` wire frames.
 */
export interface TranscriptEntry {
  readonly turnId: string;
  readonly spans: readonly TranscriptSpan[];
  readonly status: "partial" | "final";
}

export interface TranscriptViewProps {
  readonly entries: readonly TranscriptEntry[];
  /** Larger text for elder-friendly pacing (spec §14.11). */
  readonly elderMode?: boolean;
}

/**
 * Live transcript with per-span language tags visible inline (spec
 * §14.12's own demo-beat requirement — "the code-mixed utterance
 * transcribed with per-span language tags," per span, not per utterance).
 *
 * Wrapped in a `role="log" aria-live="polite"` region so a screen-reader
 * user hears new transcript content as it arrives, without this being
 * announced so aggressively that a fast-moving `transcript_partial`
 * stream becomes noise (`aria-live="polite"`, not `"assertive"` — that
 * level is reserved for `ConfirmationPrompt`, the safety-critical case).
 */
export function TranscriptView({ entries, elderMode = false }: TranscriptViewProps) {
  return (
    <div className={styles.wrapper} data-elder-mode={elderMode}>
      <div className={styles.log} role="log" aria-live="polite" aria-label="Live voice transcript">
        {entries.length === 0 && (
          <p className={styles.empty}>
            No speech yet — press and hold the mic button, or focus it and press Space/Enter, to talk to GharOS.
          </p>
        )}
        {entries.map((entry) => (
          <div key={entry.turnId} className={styles.turn} data-status={entry.status}>
            <div className={styles.spans}>
              {entry.spans.map((span, index) => (
                <LanguageSpanChip key={`${entry.turnId}-${index}`} span={span} />
              ))}
            </div>
            {entry.status === "partial" && (
              <span className={styles.partialMark} aria-label="still listening">
                …
              </span>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
