"use client";

import { useEffect, useRef } from "react";
import { Button } from "@/components/design-system/Button";
import type { ResponseAudioEvent } from "@/lib/voice-types";
import styles from "./ResponsePlayback.module.css";

/** Slower-than-normal playback for elder-friendly pacing (spec §14.11:
 * "adjustable pacing... elder-friendly pacing and volume adaptation"). */
export const ELDER_MODE_PLAYBACK_RATE = 0.8;
const NORMAL_PLAYBACK_RATE = 1;

export interface ResponsePlaybackProps {
  readonly response: ResponseAudioEvent | null;
  readonly elderMode: boolean;
}

/**
 * Plays GharOS's synthesised spoken response (real base64-decoded audio
 * via a real `<audio>` element — never a silent stand-in) while **always**
 * also rendering the response text, so a sighted user can verify what was
 * actually said versus what was transcribed, and so this surface is never
 * audio-only (spec §14.11 accessibility, and this phase's own charter).
 *
 * "Repeat on request" (spec §14.11) is the always-visible "Play again"
 * button below — a real replay of already-received audio, not a new
 * round-trip to the server, so it's honest to offer unconditionally.
 */
export function ResponsePlayback({ response, elderMode }: ResponsePlaybackProps) {
  const audioRef = useRef<HTMLAudioElement>(null);
  const playbackRate = elderMode ? ELDER_MODE_PLAYBACK_RATE : NORMAL_PLAYBACK_RATE;

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio || !response) return;
    audio.playbackRate = playbackRate;
    // Autoplay can be blocked by the browser (no prior user gesture on
    // this specific element); the "Play again" button below always
    // covers that case, so a rejected autoplay is not surfaced as an
    // error to the user.
    void audio.play().catch(() => {});
  }, [response, playbackRate]);

  if (!response) {
    return <p className={styles.empty}>GharOS hasn&apos;t responded yet.</p>;
  }

  const dataUrl = `data:${response.mimeType};base64,${response.audioB64}`;

  const replay = () => {
    const audio = audioRef.current;
    if (!audio) return;
    audio.currentTime = 0;
    audio.playbackRate = playbackRate;
    void audio.play().catch(() => {});
  };

  return (
    <div className={styles.wrapper}>
      <p className={styles.responseText} lang={response.language}>
        {response.text}
      </p>
      <audio ref={audioRef} src={dataUrl} data-testid="response-audio" />
      <Button variant="secondary" onClick={replay}>
        Play again
      </Button>
    </div>
  );
}
