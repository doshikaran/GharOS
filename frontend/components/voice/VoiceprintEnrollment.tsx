"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/design-system/Button";
import { formatDateTime } from "@/lib/approvals";
import { enrollVoiceprint, type VoiceprintEnrollmentOutcome } from "@/lib/language-profile";
import { voicePersonLabel } from "@/lib/voice-persons";
import styles from "./VoiceprintEnrollment.module.css";

/** Length of the recorded reference clip — long enough for A66 Speaker
 * Identification to have real signal, short enough to not feel like a
 * chore. */
const DEFAULT_CLIP_DURATION_MS = 4000;

export interface MediaRecorderDataEvent {
  readonly data: Blob;
}

/** Minimal shape of the browser `MediaRecorder` this component depends
 * on — small enough for a test fake, same injectable-factory discipline
 * as `lib/mic-capture.ts`. */
export interface MediaRecorderLike {
  start(): void;
  stop(): void;
  ondataavailable: ((event: MediaRecorderDataEvent) => void) | null;
  onstop: (() => void) | null;
}

export type MediaRecorderFactory = (stream: MediaStream) => MediaRecorderLike;
export type GetUserMediaLike = (constraints: MediaStreamConstraints) => Promise<MediaStream>;

function defaultGetUserMedia(constraints: MediaStreamConstraints): Promise<MediaStream> {
  return navigator.mediaDevices.getUserMedia(constraints);
}

function defaultCreateMediaRecorder(stream: MediaStream): MediaRecorderLike {
  return new MediaRecorder(stream) as unknown as MediaRecorderLike;
}

export interface VoiceprintEnrollmentProps {
  readonly baseUrl: string;
  readonly personId: string;
  readonly getUserMedia?: GetUserMediaLike;
  readonly createMediaRecorder?: MediaRecorderFactory;
  readonly clipDurationMs?: number;
}

type EnrollmentState = "idle" | "recording" | "uploading";

/**
 * Records a real short reference clip (real `getUserMedia` +
 * `MediaRecorder`, not a stub) and uploads it via
 * `lib/language-profile.ts`'s `enrollVoiceprint` — this phase's charter
 * item: "a voiceprint-enrollment endpoint (record a short reference clip
 * for a household member)." Same honest-seam discipline as
 * `LanguageProfileSettings`: the upload is a real `fetch`, and a failure
 * (including "endpoint not deployed yet") renders as a real, visible
 * failure, never a fabricated success.
 */
export function VoiceprintEnrollment({
  baseUrl,
  personId,
  getUserMedia = defaultGetUserMedia,
  createMediaRecorder = defaultCreateMediaRecorder,
  clipDurationMs = DEFAULT_CLIP_DURATION_MS,
}: VoiceprintEnrollmentProps) {
  const [state, setState] = useState<EnrollmentState>("idle");
  const [outcome, setOutcome] = useState<VoiceprintEnrollmentOutcome | null>(null);
  const streamRef = useRef<MediaStream | null>(null);

  const record = async () => {
    setOutcome(null);
    setState("recording");

    let stream: MediaStream;
    try {
      stream = await getUserMedia({ audio: true });
    } catch (err) {
      setOutcome({ status: "failure", message: err instanceof Error ? err.message : String(err) });
      setState("idle");
      return;
    }
    streamRef.current = stream;

    const recorder = createMediaRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = () => {
      stream.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      const clip = new Blob(chunks, { type: "audio/webm" });
      setState("uploading");
      void enrollVoiceprint(baseUrl, personId, clip).then((result) => {
        setOutcome(result);
        setState("idle");
      });
    };

    recorder.start();
    setTimeout(() => recorder.stop(), clipDurationMs);
  };

  return (
    <div className={styles.wrapper}>
      <h3 className={styles.heading}>Voiceprint enrollment</h3>
      <p className={styles.description}>
        Record a {Math.round(clipDurationMs / 1000)}-second reference clip of {voicePersonLabel(personId)}&apos;s
        voice so GharOS can tell household members apart when more than one person talks to it.
      </p>
      <Button variant="secondary" onClick={() => void record()} disabled={state !== "idle"}>
        {state === "recording" ? "Recording…" : state === "uploading" ? "Uploading…" : "Record voiceprint sample"}
      </Button>
      {outcome?.status === "success" && (
        <p role="status" className={styles.success}>
          Voiceprint recorded, ref <code>{outcome.voiceprintRef}</code>, enrolled {formatDateTime(outcome.enrolledAt)}.
        </p>
      )}
      {outcome?.status === "failure" && (
        <p role="alert" className={styles.error}>
          {outcome.message}
        </p>
      )}
    </div>
  );
}
