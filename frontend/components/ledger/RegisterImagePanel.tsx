"use client";

import { useEffect, useMemo, useState } from "react";
import { fetchDocumentRaw, GraphApiError } from "@/lib/graph-api";
import styles from "./RegisterImagePanel.module.css";

export interface RegisterImagePanelProps {
  readonly baseUrl: string;
  /** `PayrollResult.register_image_ref` — a `SourceDocument` id, or `null`
   * when the record's provenance carries no register image at all. */
  readonly registerImageRef: string | null;
  readonly month: string;
}

type FetchState =
  | { status: "loading" }
  | { status: "loaded"; contentType: string; bytes: Uint8Array }
  | { status: "error" };

/**
 * Renders the payroll register photograph beside the computed salary
 * figure (spec's exact wording — "showing the register image beside the
 * computed figure"). Reuses Phase 6's raw-document-fetch pattern
 * (`lib/graph-api.ts`'s `fetchDocumentRaw`, the same one
 * `SourceRegionViewer` uses) when `registerImageRef` resolves to a real,
 * live document — this is a whole-page image with no single highlighted
 * region, so `SourceRegionViewer` itself (which requires a parseable
 * `region` locator) does not apply here; this component renders the full
 * page instead.
 *
 * When the fetch fails — the id does not exist in the live backend, or no
 * backend is reachable — this falls back to a static, inline placeholder
 * image, **clearly labelled as such** (never presented as though it were
 * the real photograph) rather than silently hiding the panel.
 */
export function RegisterImagePanel({ baseUrl, registerImageRef, month }: RegisterImagePanelProps) {
  const [state, setState] = useState<FetchState>({ status: "loading" });

  // No `registerImageRef` at all is rendered directly from the prop below,
  // without ever touching `state` — this effect exists only to subscribe to
  // the one real external operation (the network fetch), never to mirror a
  // prop into state synchronously. No synchronous reset-to-loading here
  // either, matching `SourceRegionViewer`'s own established convention:
  // "loading" is simply this component's initial state on every fresh
  // mount — a caller re-pointing `registerImageRef` at a different id
  // should mount a fresh instance (`key={registerImageRef}`), not rely on
  // this effect to reset state on a dependency change.
  useEffect(() => {
    if (!registerImageRef) return undefined;
    let cancelled = false;
    fetchDocumentRaw(baseUrl, registerImageRef)
      .then((payload) => {
        if (!cancelled) setState({ status: "loaded", contentType: payload.contentType, bytes: payload.bytes });
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        // Expected in local/seeded runs: a SourceDocument node exists but
        // its raw bytes were never uploaded, so /documents/{id}/raw 404s.
        // This is a handled fallback, not an error — log at debug only so
        // it does not surface in the dev error overlay.
        const reason = err instanceof GraphApiError || err instanceof Error ? err.message : "unknown error";
        console.debug("RegisterImagePanel: no live register image, showing the placeholder", reason);
        setState({ status: "error" });
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl, registerImageRef]);

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

  if (!registerImageRef) {
    return (
      <div className={styles.panel}>
        <StaticPlaceholderIllustration />
        <p className={styles.caption} role="status">
          No register image on file for {month}.
        </p>
      </div>
    );
  }

  if (state.status === "loading") {
    return (
      <div className={styles.panel}>
        <p className={styles.status} role="status">
          Loading {month}&apos;s register photograph…
        </p>
      </div>
    );
  }

  if (state.status === "loaded" && objectUrl) {
    return (
      <div className={styles.panel}>
        {/* eslint-disable-next-line @next/next/no-img-element -- raw
            document bytes served from the API, not a Next.js-optimisable
            static asset (same rationale as SourceRegionViewer). */}
        <img src={objectUrl} alt={`${month} handwritten attendance register`} className={styles.image} />
        <p className={styles.caption}>Live source document: {registerImageRef}</p>
      </div>
    );
  }

  // `state.status === "error"` — the live fetch failed (the id does not
  // exist in the live backend, or no backend is reachable). Render a
  // clearly-labelled static placeholder rather than silently omitting the
  // register image entirely.
  return (
    <div className={styles.panel}>
      <StaticPlaceholderIllustration />
      <p className={styles.caption} role="status">
        Static placeholder, no scanned register page is stored for {month} in this environment.
      </p>
    </div>
  );
}

/** A small inline SVG standing in for a photographed lined register page —
 * self-contained, never a real document, and never rendered without the
 * caption above making that explicit. */
function StaticPlaceholderIllustration() {
  return (
    <svg
      viewBox="0 0 200 140"
      className={styles.placeholderImage}
      role="img"
      aria-label="Static placeholder illustration of a lined attendance register page"
    >
      <rect x="4" y="4" width="192" height="132" rx="4" className={styles.placeholderPage} />
      {[24, 40, 56, 72, 88, 104, 120].map((y) => (
        <line key={y} x1="16" y1={y} x2="184" y2={y} className={styles.placeholderLine} />
      ))}
      <line x1="40" y1="4" x2="40" y2="136" className={styles.placeholderMargin} />
    </svg>
  );
}
