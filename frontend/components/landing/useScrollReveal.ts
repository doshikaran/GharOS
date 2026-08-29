"use client";

import { useEffect, useRef, useState } from "react";

export interface UseScrollRevealOptions {
  /** Fraction of the element that must be on-screen before it reveals.
   * Default 0.15 — early enough that a chapter is legible well before it's
   * fully scrolled into the middle of the viewport. */
  threshold?: number;
  /** Root margin passed straight to `IntersectionObserver` — lets a caller
   * reveal slightly before/after the literal viewport edge. */
  rootMargin?: string;
}

/**
 * Scroll-triggered reveal, built for the landing page's staggered chapter
 * animation (`docs/design/2026-08-29-redesign-brief.md`, "The journey").
 * `IntersectionObserver`-backed, reveal-once (an element that has already
 * revealed never re-hides on scrolling back past it — a marketing page
 * that re-animates every scroll direction reads as gimmicky, not elegant).
 *
 * Deliberately does NOT read `prefers-reduced-motion` itself: this hook
 * only ever flips `visible` from `false` to `true`, so the reduced-motion
 * "no animation, content just appears" requirement is satisfied entirely
 * in CSS (the same convention `LiveCallTranscript.module.css` already
 * uses) — the consuming stylesheet unconditionally shows the element at
 * full opacity under `@media (prefers-reduced-motion: reduce)` regardless
 * of this hook's returned value. That keeps "was it actually skipped"
 * verifiable by reading CSS alone, with no JS/CSS split-brain risk.
 *
 * SSR/no-`IntersectionObserver` safe: if the API is unavailable (very old
 * browsers, or a non-DOM test environment that hasn't polyfilled it),
 * content reveals immediately rather than staying permanently hidden.
 */
export function useScrollReveal<T extends HTMLElement>(
  options: UseScrollRevealOptions = {},
): { ref: React.RefObject<T | null>; visible: boolean } {
  const { threshold = 0.15, rootMargin = "0px 0px -10% 0px" } = options;
  const ref = useRef<T | null>(null);
  // Computed once, in the initializer rather than an effect: an effect
  // that calls setState synchronously on every run causes a cascading
  // extra render for no benefit here, and this value can never change
  // for the lifetime of a given runtime anyway.
  const [visible, setVisible] = useState(() => typeof IntersectionObserver === "undefined");

  useEffect(() => {
    const node = ref.current;
    if (!node || typeof IntersectionObserver === "undefined") return;

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setVisible(true);
            observer.disconnect();
          }
        }
      },
      { threshold, rootMargin },
    );

    observer.observe(node);
    return () => observer.disconnect();
  }, [threshold, rootMargin]);

  return { ref, visible };
}
