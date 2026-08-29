"use client";

import { useState } from "react";
import { FolderInput } from "lucide-react";
import { Button } from "@/components/design-system/Button";
import {
  GOOGLE_APP_ID,
  GOOGLE_PICKER_API_KEY,
  fetchPickerToken,
  isDrivePickerConfigured,
  loadGooglePicker,
  openDrivePicker,
} from "@/lib/drive-picker";
import styles from "./DrivePickerButton.module.css";

export interface DrivePickerButtonProps {
  readonly baseUrl: string;
  /** The connected Google account's principal, or `null` if Google is
   * not connected. */
  readonly googlePrincipal: string | null;
  readonly onPicked: (driveFileIds: readonly string[]) => void;
  readonly running: boolean;
}

/**
 * Google Picker (`drive.file` scope) entry point (PHASES.md Phase 14.5,
 * E4 brief). Picked file ids are POSTed to `POST /ingest`; the server
 * fetches the bytes. Degrades gracefully, with the reason shown, when the
 * browser-side Picker config is absent or the loader is blocked — the
 * drag-and-drop path still covers file ingestion.
 */
export function DrivePickerButton({ baseUrl, googlePrincipal, onPicked, running }: DrivePickerButtonProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!isDrivePickerConfigured()) {
    return (
      <p className={styles.degraded}>
        The Google Drive picker needs browser configuration (<span className={styles.mono}>NEXT_PUBLIC_GOOGLE_PICKER_API_KEY</span>{" "}
        and <span className={styles.mono}>NEXT_PUBLIC_GOOGLE_APP_ID</span>) before it can be used. Drag-and-drop
        upload above works without it.
      </p>
    );
  }

  if (googlePrincipal === null) {
    return <p className={styles.degraded}>Connect Google above to pick files from Drive.</p>;
  }

  async function handleClick() {
    setError(null);
    setBusy(true);
    try {
      await loadGooglePicker();
      const token = await fetchPickerToken(baseUrl, googlePrincipal as string);
      openDrivePicker({
        oauthToken: token.access_token,
        apiKey: GOOGLE_PICKER_API_KEY,
        appId: GOOGLE_APP_ID,
        onPicked: (files) => onPicked(files.map((file) => file.id)),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "The Drive picker could not be opened.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={styles.wrap}>
      <Button variant="secondary" onClick={handleClick} disabled={busy || running}>
        <FolderInput size={16} aria-hidden="true" />
        {busy ? "Opening Drive…" : "Pick from Google Drive"}
      </Button>
      {error && (
        <p className={styles.error} role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
