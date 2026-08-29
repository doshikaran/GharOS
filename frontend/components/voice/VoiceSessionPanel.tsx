"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { IngestionRunView } from "@/components/connections/IngestionRunView";
import { useApprovalQueueCount } from "@/components/shell/useApprovalQueueCount";
import type { IngestionRunResult } from "@/lib/connections";
import { MicCapture, type MicCaptureHandlers, type MicPermissionState } from "@/lib/mic-capture";
import { VoiceSessionClient, type VoiceSessionHandlers } from "@/lib/voice-session";
import type { ConfirmationPromptEvent, ResponseAudioEvent, SessionState, VoiceServerEvent } from "@/lib/voice-types";
import { AccessibilityControls } from "./AccessibilityControls";
import { ConfirmationPrompt } from "./ConfirmationPrompt";
import { MicControl } from "./MicControl";
import { ResponsePlayback } from "./ResponsePlayback";
import { SessionStateIndicator } from "./SessionStateIndicator";
import { TranscriptView, type TranscriptEntry } from "./TranscriptView";
import styles from "./VoiceSessionPanel.module.css";

/** Minimal interfaces this panel depends on — satisfied by the real
 * `VoiceSessionClient`/`MicCapture` by default, and by test fakes via the
 * injectable factory props below (same discipline as every other
 * WebSocket/EventSource client in `lib/`). */
export interface VoiceSessionClientLike {
  connect(): void;
  close(): void;
  sendAudioFrame(frame: ArrayBuffer): void;
}
export interface MicCaptureLike {
  start(): Promise<void>;
  stop(): void;
}

export interface VoiceSessionPanelProps {
  readonly baseUrl: string;
  readonly createSessionClient?: (baseUrl: string, handlers: VoiceSessionHandlers) => VoiceSessionClientLike;
  readonly createMicCapture?: (handlers: MicCaptureHandlers) => MicCaptureLike;
}

function defaultCreateSessionClient(baseUrl: string, handlers: VoiceSessionHandlers): VoiceSessionClientLike {
  return new VoiceSessionClient(baseUrl, handlers);
}

function defaultCreateMicCapture(handlers: MicCaptureHandlers): MicCaptureLike {
  return new MicCapture(handlers);
}

/**
 * The live voice session surface (this phase's E4 charter, item 1-3):
 * connects to the real `wss://.../voice/session` endpoint on mount, wires
 * a real mic capture pipeline to it, and renders the session's real state,
 * live per-span transcript, safety-critical confirmation prompts, and
 * spoken responses — end to end, no mocked/fixture data path.
 *
 * Owns the one piece of session-manager-adjacent logic that belongs on
 * the client rather than the server: **barge-in**. Per ADR-020 Decision 3,
 * "a barge-in is the client sending new audio frames while session_state
 * == 'speaking', which cancels in-flight TTS playback client-side." This
 * component is what makes that literally true — starting to listen while
 * `sessionState === "speaking"` immediately pauses the `<audio>` element
 * before any new `session_state` frame confirms the server's own turn
 * change, and flags `interrupted` so `SessionStateIndicator` shows it.
 */
export function VoiceSessionPanel({
  baseUrl,
  createSessionClient = defaultCreateSessionClient,
  createMicCapture = defaultCreateMicCapture,
}: VoiceSessionPanelProps) {
  const [sessionState, setSessionState] = useState<SessionState>("closed");
  const [interrupted, setInterrupted] = useState(false);
  const [micPermission, setMicPermission] = useState<MicPermissionState>("idle");
  const [continuousMode, setContinuousMode] = useState(false);
  const [listening, setListening] = useState(false);
  const [elderMode, setElderMode] = useState(false);
  const [entries, setEntries] = useState<readonly TranscriptEntry[]>([]);
  const [confirmation, setConfirmation] = useState<ConfirmationPromptEvent | null>(null);
  const [response, setResponse] = useState<ResponseAudioEvent | null>(null);
  const [ingestionRun, setIngestionRun] = useState<IngestionRunResult | null>(null);
  const [connectionError, setConnectionError] = useState<string | null>(null);

  const audioPauseRef = useRef<() => void>(() => {});
  const sessionClientRef = useRef<VoiceSessionClientLike | null>(null);
  const micCaptureRef = useRef<MicCaptureLike | null>(null);

  const pendingApprovalCount = useApprovalQueueCount();

  /** A confirmation prompt is cleared once a *different* turn produces a
   * new confirmation prompt or spoken response — the wire contract has no
   * explicit "this confirmation is resolved" frame, so a turn change is
   * this component's honest, documented signal that the session moved
   * on. See `ConfirmationPrompt`'s own doc comment for why this component
   * never resolves it via a client-side click instead. */
  const handleEvent = useCallback((event: VoiceServerEvent) => {
    switch (event.type) {
      case "session_state": {
        setSessionState(event.state);
        if (event.state !== "speaking") setInterrupted(false);
        break;
      }
      case "transcript_partial": {
        setEntries((previous) => {
          const withoutPartial = previous.filter((entry) => entry.status !== "partial" || entry.turnId !== event.turnId);
          return [...withoutPartial, { turnId: event.turnId, spans: event.spans, status: "partial" }];
        });
        break;
      }
      case "transcript_final": {
        setEntries((previous) => [
          ...previous.filter((entry) => entry.turnId !== event.turnId),
          { turnId: event.turnId, spans: event.spans, status: "final" },
        ]);
        break;
      }
      case "confirmation_prompt": {
        setConfirmation({ type: "confirmation_prompt", text: event.text, requiresAffirmative: true, turnId: event.turnId });
        break;
      }
      case "response_audio": {
        setResponse(event);
        setConfirmation((previous) => (previous && previous.turnId !== event.turnId ? null : previous));
        break;
      }
      case "error": {
        setConnectionError(`${event.code}: ${event.message}`);
        break;
      }
      case "ingestion_run": {
        // "Scan my Gmail" spoken aloud (A67 → the ingestion orchestrator,
        // ADR-023 §7) surfaces here in the exact same run view the
        // `/connections` text path renders.
        setIngestionRun(event.run);
        break;
      }
    }
  }, []);

  useEffect(() => {
    const handlers: VoiceSessionHandlers = {
      onEvent: handleEvent,
      onOpen: () => setConnectionError(null),
      onClose: () => setSessionState("closed"),
      onError: (error) => setConnectionError(error.message),
    };
    const client = createSessionClient(baseUrl, handlers);
    sessionClientRef.current = client;
    client.connect();
    return () => {
      client.close();
      sessionClientRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- createSessionClient/handleEvent are stable for the panel's lifetime; re-running this effect on every render would tear down and reopen the live session.
  }, [baseUrl]);

  const startListening = useCallback(() => {
    if (sessionState === "speaking") {
      audioPauseRef.current();
      setInterrupted(true);
    }
    const micHandlers: MicCaptureHandlers = {
      onFrame: (frame) => sessionClientRef.current?.sendAudioFrame(frame),
      onPermissionChange: setMicPermission,
      onError: (error) => setConnectionError(error.message),
    };
    const mic = createMicCapture(micHandlers);
    micCaptureRef.current = mic;
    setListening(true);
    void mic.start();
  }, [sessionState, createMicCapture]);

  const stopListening = useCallback(() => {
    micCaptureRef.current?.stop();
    micCaptureRef.current = null;
    setListening(false);
  }, []);

  useEffect(() => () => micCaptureRef.current?.stop(), []);

  const registerAudioPause = useCallback((pause: () => void) => {
    audioPauseRef.current = pause;
  }, []);

  return (
    <div className={styles.panel}>
      {connectionError && (
        <p role="status" className={styles.connectionError}>
          Voice session issue: {connectionError}
        </p>
      )}

      <SessionStateIndicator state={sessionState} interrupted={interrupted} />

      <MicControl
        listening={listening}
        permission={micPermission}
        continuousMode={continuousMode}
        onContinuousModeChange={setContinuousMode}
        onStart={startListening}
        onStop={stopListening}
      />

      <TranscriptView entries={entries} elderMode={elderMode} />

      {confirmation && <ConfirmationPrompt prompt={confirmation} pendingApprovalCount={pendingApprovalCount} />}

      <ResponsePlaybackWithPauseRegistration response={response} elderMode={elderMode} registerAudioPause={registerAudioPause} />

      {ingestionRun && (
        <section className={styles.ingestionRun} aria-label="Mailbox scan result">
          <h3 className={styles.ingestionRunHeading}>Mailbox scan</h3>
          <IngestionRunView state={{ phase: "done", run: ingestionRun, liveNodeIds: [] }} />
        </section>
      )}

      <AccessibilityControls elderMode={elderMode} onElderModeChange={setElderMode} />
    </div>
  );
}

/**
 * Thin wrapper giving `VoiceSessionPanel` an imperative "pause the current
 * response's audio" hook for barge-in, without `ResponsePlayback` itself
 * needing to know anything about sessions or barge-in — it stays a plain
 * "play this audio, show this text" component.
 */
function ResponsePlaybackWithPauseRegistration({
  response,
  elderMode,
  registerAudioPause,
}: {
  response: ResponseAudioEvent | null;
  elderMode: boolean;
  registerAudioPause: (pause: () => void) => void;
}) {
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    registerAudioPause(() => {
      const audio = wrapperRef.current?.querySelector("audio");
      audio?.pause();
    });
  }, [registerAudioPause]);

  return (
    <div ref={wrapperRef}>
      <ResponsePlayback response={response} elderMode={elderMode} />
    </div>
  );
}
