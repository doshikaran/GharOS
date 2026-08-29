"use client";

import { Mic, MicOff } from "lucide-react";
import type { KeyboardEvent } from "react";
import { Toggle } from "@/components/design-system/Toggle";
import type { MicPermissionState } from "@/lib/mic-capture";
import styles from "./MicControl.module.css";

export interface MicControlProps {
  /** True while audio frames are actively being streamed — either the
   * push-to-talk button is held, or continuous mode is switched on. */
  readonly listening: boolean;
  readonly permission: MicPermissionState;
  readonly continuousMode: boolean;
  readonly onContinuousModeChange: (next: boolean) => void;
  readonly onStart: () => void;
  readonly onStop: () => void;
}

/**
 * The mic control — push-to-talk (hold to talk, spec §14.9) or continuous
 * "hands-free" session (spec §14.9's other listed mode), switchable via
 * the adjacent toggle. Built on a real `<button>` so keyboard operation
 * (Space/Enter) and screen-reader semantics come for free; push-to-talk
 * additionally wires real `mousedown`/`mouseup`/`touchstart`/`touchend`
 * pairs plus matching `keydown`/`keyup` handling so the whole surface is
 * usable without a mouse (spec §14.11).
 *
 * Never plays a permission failure or a slow re-ask as an error — a
 * denied/unavailable mic renders as a plain, calm instruction
 * (`role="alert"` only because it needs to be announced, not because it's
 * styled as a failure state), matching spec §14.11's "patient re-prompting
 * without penalty" for every other case.
 */
export function MicControl({
  listening,
  permission,
  continuousMode,
  onContinuousModeChange,
  onStart,
  onStop,
}: MicControlProps) {
  const disabled = permission === "denied";

  const handlePressStart = () => {
    if (!continuousMode && !disabled) onStart();
  };
  const handlePressEnd = () => {
    if (!continuousMode) onStop();
  };
  const handleClick = () => {
    if (continuousMode && !disabled) {
      if (listening) onStop();
      else onStart();
    }
  };
  const handleKeyDown = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (continuousMode || event.repeat) return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      handlePressStart();
    }
  };
  const handleKeyUp = (event: KeyboardEvent<HTMLButtonElement>) => {
    if (continuousMode) return;
    if (event.key === " " || event.key === "Enter") {
      event.preventDefault();
      handlePressEnd();
    }
  };

  const label = continuousMode
    ? listening
      ? "Stop hands-free listening"
      : "Start hands-free listening"
    : "Hold to talk to GharOS";

  return (
    <div className={styles.wrapper}>
      <button
        type="button"
        className={styles.micButton}
        data-listening={listening}
        aria-pressed={listening}
        disabled={disabled}
        onMouseDown={handlePressStart}
        onMouseUp={handlePressEnd}
        onMouseLeave={() => {
          if (!continuousMode && listening) onStop();
        }}
        onTouchStart={handlePressStart}
        onTouchEnd={handlePressEnd}
        onClick={handleClick}
        onKeyDown={handleKeyDown}
        onKeyUp={handleKeyUp}
      >
        {listening ? <MicOff aria-hidden="true" /> : <Mic aria-hidden="true" />}
        <span className={styles.buttonLabel}>{label}</span>
      </button>

      <Toggle checked={continuousMode} onChange={onContinuousModeChange} label="Hands-free (continuous) mode" disabled={listening} />

      {permission === "denied" && (
        <p role="alert" className={styles.notice}>
          Microphone access was denied. Allow microphone access for this site in your browser settings to talk to GharOS.
        </p>
      )}
      {permission === "error" && (
        <p role="alert" className={styles.notice}>
          Could not reach a microphone on this device. Try again, or use the visual surface directly.
        </p>
      )}
    </div>
  );
}
