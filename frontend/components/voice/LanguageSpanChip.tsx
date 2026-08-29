import { languageDisplayLabel, type TranscriptSpan } from "@/lib/voice-types";
import styles from "./LanguageSpanChip.module.css";

/**
 * Below this self-reported confidence, a span is flagged visibly rather
 * than rendered as if it were fully trusted — spec §14.10: "Low ASR
 * confidence on any consequential token forces a clarifying question,
 * never a guess." This constant governs only the visual flag; the actual
 * decision to ask a clarifying question is a backend (A67/A68) concern.
 */
export const LOW_CONFIDENCE_THRESHOLD = 0.6;

export interface LanguageSpanChipProps {
  readonly span: TranscriptSpan;
}

/**
 * One per-span language tag — the spec §14.12 demo-beat requirement
 * rendered literally: "the code-mixed utterance transcribed with per-span
 * language tags," not one tag for the whole utterance. A single Hinglish
 * sentence renders as several of these side by side, each carrying its
 * own identified language.
 */
export function LanguageSpanChip({ span }: LanguageSpanChipProps) {
  const lowConfidence = span.confidence < LOW_CONFIDENCE_THRESHOLD;
  return (
    <span className={styles.chip} data-low-confidence={lowConfidence}>
      <span className={styles.text}>{span.text}</span>
      <span className={styles.tag}>
        {languageDisplayLabel(span.language)}
        {lowConfidence && (
          <span className={styles.lowConfidenceMark} aria-label="low confidence — may need to be repeated">
            {" "}
            ⚠
          </span>
        )}
      </span>
    </span>
  );
}
