"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchDocumentRaw, GraphApiError } from "@/lib/graph-api";
import { decodeHighlightedTextSpan, MalformedRegionError, parseRegion } from "@/lib/region-locator";
import styles from "./SourceRegionViewer.module.css";

export interface SourceRegionViewerProps {
  readonly baseUrl: string;
  readonly documentId: string;
  readonly region: string;
}

type LoadState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; contentType: string; bytes: Uint8Array };

/**
 * Fetches `/documents/{id}/raw` and renders the source with `region`
 * highlighted directly on it — not just displayed as a locator string with
 * nothing to point it at. Handles both region-locator conventions
 * (`lib/region-locator.ts`): a substring highlight for text-shaped
 * documents (byte-offset span), an overlay rectangle for image-shaped
 * documents (page + bbox).
 */
export function SourceRegionViewer({ baseUrl, documentId, region }: SourceRegionViewerProps) {
  const [state, setState] = useState<LoadState>({ status: "loading" });
  const [naturalSize, setNaturalSize] = useState<{ width: number; height: number } | null>(null);

  // No synchronous reset-to-loading here: the caller (`NodeInspector`)
  // mounts one `SourceRegionViewer` per node via `key={node.id}`, so
  // "loading" is simply this component's initial state on every fresh
  // node selection.
  useEffect(() => {
    let cancelled = false;

    fetchDocumentRaw(baseUrl, documentId)
      .then((payload) => {
        if (!cancelled) setState({ status: "loaded", contentType: payload.contentType, bytes: payload.bytes });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const message =
          err instanceof GraphApiError || err instanceof Error ? err.message : "Failed to load source document.";
        setState({ status: "error", message });
      });

    return () => {
      cancelled = true;
    };
  }, [baseUrl, documentId]);

  const objectUrl = useMemo(() => {
    if (state.status !== "loaded" || !state.contentType.startsWith("image/")) return null;
    const blob = new Blob([new Uint8Array(state.bytes)], { type: state.contentType });
    return URL.createObjectURL(blob);
  }, [state]);

  useEffect(() => {
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [objectUrl]);

  if (state.status === "loading") {
    return (
      <p className={styles.status} role="status">
        Loading source document…
      </p>
    );
  }

  if (state.status === "error") {
    return (
      <p className={styles.status} role="alert">
        Could not load the source document: {state.message}
      </p>
    );
  }

  let parsedRegion;
  try {
    parsedRegion = parseRegion(region);
  } catch (err) {
    const message = err instanceof MalformedRegionError ? err.message : "Malformed region.";
    return (
      <p className={styles.status} role="alert">
        {message}
      </p>
    );
  }

  const isText = state.contentType.startsWith("text/");
  const isImage = state.contentType.startsWith("image/");

  if (isText && parsedRegion.kind === "text-span") {
    const { before, highlighted, after } = decodeHighlightedTextSpan(state.bytes, parsedRegion);
    return (
      <pre className={styles.textDocument}>
        {before}
        <mark className={styles.highlight}>{highlighted}</mark>
        {after}
      </pre>
    );
  }

  if (isImage && parsedRegion.kind === "page-bbox" && objectUrl) {
    const { bbox } = parsedRegion;
    const overlayStyle =
      naturalSize && naturalSize.width > 0 && naturalSize.height > 0
        ? {
            left: `${(bbox.x0 / naturalSize.width) * 100}%`,
            top: `${(bbox.y0 / naturalSize.height) * 100}%`,
            width: `${((bbox.x1 - bbox.x0) / naturalSize.width) * 100}%`,
            height: `${((bbox.y1 - bbox.y0) / naturalSize.height) * 100}%`,
          }
        : undefined;
    return (
      <div className={styles.imageDocument}>
        <p className={styles.pageLabel}>Page {parsedRegion.page}</p>
        <div className={styles.imageFrame}>
          {/* eslint-disable-next-line @next/next/no-img-element -- raw
              document bytes served from the API, not a Next.js-optimisable
              static asset. */}
          <img
            src={objectUrl}
            alt="Source document"
            className={styles.image}
            onLoad={(event) => {
              const target = event.currentTarget;
              setNaturalSize({ width: target.naturalWidth, height: target.naturalHeight });
            }}
          />
          {overlayStyle && <div className={styles.overlay} style={overlayStyle} aria-hidden="true" />}
        </div>
      </div>
    );
  }

  return (
    <p className={styles.status} role="alert">
      This document&apos;s content type ({state.contentType}) does not match its region locator convention.
    </p>
  );
}
