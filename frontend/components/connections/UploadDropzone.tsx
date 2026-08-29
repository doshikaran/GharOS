"use client";

import { useRef, useState, type DragEvent } from "react";
import { UploadCloud } from "lucide-react";
import styles from "./UploadDropzone.module.css";

const ACCEPTED_TYPES = ["image/", "application/pdf"];

function acceptable(file: File): boolean {
  return ACCEPTED_TYPES.some((prefix) => file.type.startsWith(prefix) || file.type === prefix);
}

export interface UploadDropzoneProps {
  readonly onFiles: (files: readonly File[]) => void;
  readonly running: boolean;
}

/**
 * Drag-and-drop (or click-to-choose) zone for images and PDFs. Each
 * selection is one `POST /ingest` multipart submission through the same
 * orchestrator wire as a mailbox scan (ADR-023 §1).
 */
export function UploadDropzone({ onFiles, running }: UploadDropzoneProps) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [dragActive, setDragActive] = useState(false);
  const [rejectedCount, setRejectedCount] = useState(0);

  function handleFileList(list: FileList | null) {
    if (!list || list.length === 0) return;
    const all = Array.from(list);
    const usable = all.filter(acceptable);
    setRejectedCount(all.length - usable.length);
    if (usable.length > 0) onFiles(usable);
  }

  function handleDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragActive(false);
    if (running) return;
    handleFileList(event.dataTransfer.files);
  }

  return (
    <div
      className={styles.zone}
      data-drag-active={dragActive}
      onDragOver={(event) => {
        event.preventDefault();
        if (!running) setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={handleDrop}
    >
      <UploadCloud size={28} aria-hidden="true" className={styles.icon} />
      <p className={styles.headline}>Drop a receipt, bill, letter, or PDF here</p>
      <p className={styles.sub}>Images and PDF files. They go through the same pipeline as scanned mail.</p>

      <input
        ref={inputRef}
        id="upload-file-input"
        className={styles.input}
        type="file"
        accept="image/*,application/pdf"
        multiple
        disabled={running}
        onChange={(event) => {
          handleFileList(event.target.files);
          event.target.value = "";
        }}
      />
      <label htmlFor="upload-file-input" className={styles.chooseButton} data-disabled={running}>
        Choose files
      </label>

      {rejectedCount > 0 && (
        <p className={styles.rejected} role="status">
          {rejectedCount} {rejectedCount === 1 ? "file was" : "files were"} skipped: only images and PDFs are
          accepted.
        </p>
      )}
    </div>
  );
}
