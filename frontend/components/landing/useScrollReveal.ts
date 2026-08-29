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
 *
 * The initial value is always `false`, on both server and client — never
 * computed from `typeof IntersectionObserver`, which is `"undefined"`
 * during SSR (no DOM globals in Node) but defined in every real browser,
 * so branching on it in `useState`'s initializer made the server-rendered
 * HTML (`data-visible="true"`) permanently disagree with React's own
 * first client render (`data-visible="false"`) — a real hydration
 * mismatch, not a cosmetic one. The no-`IntersectionObserver` fallback
 * below now runs inside the effect instead (client-only, post-mount by
 * definition), which causes one ordinary extra client render rather than
 * a hydration-time disagreement.
 */
export function useScrollReveal<T extends HTMLElement>(
  options: UseScrollRevealOptions = {},
): { ref: React.RefObject<T | null>; visible: boolean } {
  const { threshold = 0.15, rootMargin = "0px 0px -10% 0px" } = options;
  const ref = useRef<T | null>(null);
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") {
      // Same documented hydration-safety pattern as ThemeSwitcher.tsx:
      // this fact is only knowable on the client, one tick past mount —
      // computing it in the initializer instead is what caused the
      // hydration mismatch this effect exists to avoid.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setVisible(true);
      return;
    }
    const node = ref.current;
    if (!node) return;

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
