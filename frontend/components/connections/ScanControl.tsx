"use client";

import { ScanLine } from "lucide-react";
import { Button } from "@/components/design-system/Button";
import { ingestionSourceLabel, type IngestionSourceKind } from "@/lib/connections";
import { VOICE_HOUSEHOLD_PERSONS } from "@/lib/voice-persons";
import styles from "./ScanControl.module.css";

/** The scan window every "scan the last 24 hours" trigger uses (seconds),
 * matching `contracts.ingestion` / PHASES.md Phase 14.5's demo window. */
export const SCAN_WINDOW_SECONDS = 86_400;

export interface ScanControlProps {
  /** The scanning source kinds backed by an active connection. */
  readonly sources: readonly IngestionSourceKind[];
  /** The connected-account identity the scan authenticates as
   * (`IngestionRequest.principal`), or `null` when nothing is connected. */
  readonly principal: string | null;
  /** PERSON NodeId recorded as `IngestionRequest.triggered_by`. */
  readonly triggeredBy: string;
  readonly onTriggeredByChange: (personId: string) => void;
  readonly onScan: () => void;
  readonly running: boolean;
}

/**
 * The "Scan the last 24 hours" trigger (PHASES.md Phase 14.5, E4 brief).
 * Disabled when nothing is connected. Issues one `POST /ingest` window
 * scan across every connected mailbox for the chosen household member.
 */
export function ScanControl({
  sources,
  principal,
  triggeredBy,
  onTriggeredByChange,
  onScan,
  running,
}: ScanControlProps) {
  const nothingConnected = sources.length === 0 || principal === null;
  const disabled = running || nothingConnected;

  return (
    <div className={styles.control}>
      <div className={styles.field}>
        <label htmlFor="scan-triggered-by" className={styles.label}>
          Run as
        </label>
        <select
          id="scan-triggered-by"
          className={styles.select}
          value={triggeredBy}
          onChange={(event) => onTriggeredByChange(event.target.value)}
        >
          {VOICE_HOUSEHOLD_PERSONS.map((person) => (
            <option key={person.personId} value={person.personId}>
              {person.displayName} ({person.relationshipToHousehold})
            </option>
          ))}
        </select>
      </div>

      <div className={styles.action}>
        <Button variant="primary" onClick={onScan} disabled={disabled}>
          <ScanLine size={16} aria-hidden="true" />
          {running ? "Scanning…" : "Scan the last 24 hours"}
        </Button>
        {nothingConnected ? (
          <p className={styles.note}>Connect Gmail or Outlook above to enable a scan.</p>
        ) : (
          <p className={styles.note}>
            Will scan {sources.map(ingestionSourceLabel).join(" and ")} as{" "}
            <span className={styles.mono}>{principal}</span>.
          </p>
        )}
      </div>
    </div>
  );
}
