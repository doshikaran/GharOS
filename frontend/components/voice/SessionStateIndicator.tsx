import { Ear, Loader2, Volume2, VolumeOff } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/design-system/Badge";
import type { SessionState } from "@/lib/voice-types";
import styles from "./SessionStateIndicator.module.css";

export interface SessionStateIndicatorProps {
  readonly state: SessionState;
  /**
   * True for the brief window after the household member started talking
   * while `state` was still `"speaking"` — a real barge-in (ADR-020
   * Decision 3: "a barge-in is the client sending new audio frames while
   * session_state == 'speaking', which cancels in-flight TTS playback
   * client-side"). This is what makes the interruption visible rather
   * than cosmetic: `VoiceSessionPanel` sets it the instant it pauses
   * local audio playback, before any new `session_state` frame confirms
   * the server's own turn change.
   */
  readonly interrupted: boolean;
}

const STATE_LABEL: Record<SessionState, string> = {
  listening: "Listening",
  processing: "Thinking",
  speaking: "Speaking",
  closed: "Not connected",
};

const STATE_VARIANT: Record<SessionState, BadgeVariant> = {
  listening: "info",
  processing: "brass",
  speaking: "royal",
  closed: "neutral",
};

const STATE_ICON: Record<SessionState, typeof Ear> = {
  listening: Ear,
  processing: Loader2,
  speaking: Volume2,
  closed: VolumeOff,
};

/**
 * Reflects the voice session's real `session_state` server frames
 * (ADR-020 Decision 3) — never a locally-guessed state. An
 * `aria-live="polite"` region so a screen-reader user hears every state
 * change without needing to keep visual focus on this indicator, and a
 * distinct, visible "Interrupted" callout when a barge-in actually
 * happened, so the interruption reads as a real mechanic rather than a
 * silent no-op.
 */
export function SessionStateIndicator({ state, interrupted }: SessionStateIndicatorProps) {
  const Icon = STATE_ICON[state];
  return (
    <div className={styles.wrapper} role="status" aria-live="polite">
      <Badge variant={STATE_VARIANT[state]} className={styles.badge} data-session-state={state}>
        <Icon aria-hidden="true" className={state === "processing" ? styles.spinning : undefined} size={16} />
        {STATE_LABEL[state]}
      </Badge>
      {interrupted && (
        <span className={styles.interrupted} data-testid="barge-in-indicator">
          Interrupted — GharOS stopped talking because you started speaking.
        </span>
      )}
    </div>
  );
}
