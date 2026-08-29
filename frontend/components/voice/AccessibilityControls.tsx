"use client";

import { Toggle } from "@/components/design-system/Toggle";
import styles from "./AccessibilityControls.module.css";

export interface AccessibilityControlsProps {
  readonly elderMode: boolean;
  readonly onElderModeChange: (next: boolean) => void;
}

/**
 * Spec §14.11's accessibility requirements, made concrete as one toggle
 * plus a plain-language explanation of what it changes: slower TTS
 * playback (`ResponsePlayback`'s `ELDER_MODE_PLAYBACK_RATE`) and larger
 * transcript text (`TranscriptView`'s `data-elder-mode`). "Patient
 * re-prompting without penalty" isn't a separate control here — it's the
 * standing rule, honoured throughout this surface, that no repeated or
 * slow attempt is ever styled as an error (see `MicControl`'s own doc
 * comment).
 */
export function AccessibilityControls({ elderMode, onElderModeChange }: AccessibilityControlsProps) {
  return (
    <div className={styles.wrapper}>
      <Toggle checked={elderMode} onChange={onElderModeChange} label="Elder-friendly pacing" />
      <p className={styles.description}>
        Slows spoken responses and enlarges the transcript text. There is never a penalty for asking GharOS to
        repeat itself, or for needing more than one try to be understood.
      </p>
    </div>
  );
}
