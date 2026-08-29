"use client";

import { useEffect, useRef, useState } from "react";
import { ApprovalCard } from "@/components/approvals/ApprovalCard";
import { ConfirmationPrompt } from "@/components/voice/ConfirmationPrompt";
import { SessionStateIndicator } from "@/components/voice/SessionStateIndicator";
import { TranscriptView } from "@/components/voice/TranscriptView";
import {
  LANDING_APPROVAL_ITEM,
  LANDING_APPROVAL_NOW,
  LANDING_CONFIRMATION_PROMPT,
  LANDING_TRANSCRIPT_ENTRIES,
} from "./landingFixtures";
import styles from "./HeroDevice.module.css";

/** The three scrubbed screen states, in scroll order. */
const STATE_COUNT = 3;

/** Which state the page composes statically around under
 * `prefers-reduced-motion: reduce` — the read-back register (state 2 of
 * 3, index 1), per the design plan. */
const REDUCED_MOTION_STATE = 1;

/** Opening tilt of the lid, degrees — settles to 0 as the scrub begins. */
const TILT_MAX_DEG = 8;

/** Fraction of the scrub over which the tilt fully settles. */
const TILT_SETTLE_PROGRESS = 0.4;

const STATE_CAPTIONS: readonly string[] = [
  "Heard in two languages, tagged per span",
  "Read back in full — queued, never auto-paid",
  "The approval gate, evidence attached",
];

/**
 * The landing page's signature: a pure-CSS laptop whose screen shows the
 * REAL product components (TranscriptView, ConfirmationPrompt,
 * ApprovalCard — never mockups) rendering one continuous transaction,
 * scrubbed through three states as the visitor scrolls the first
 * viewport while the lid tilts ~8°→0° and settles.
 *
 * Mechanics, per the frozen design plan:
 * - Scrub runs on a passive scroll listener + requestAnimationFrame; the
 *   only animated properties are `transform` (lid tilt, applied directly
 *   to a ref, no per-frame React render) and `opacity` (state
 *   cross-fade, a data attribute + CSS transition).
 * - The device sits `position: sticky` inside a tall track so all three
 *   states are actually seen during the scrub — the movement itself is
 *   native scroll, not animation.
 * - Under `prefers-reduced-motion: reduce` the component composes
 *   statically: normal document flow (no tall track, no sticky), no
 *   tilt, no listeners, and ONLY the read-back state rendered.
 * - The screen's contents are a decorative product illustration, so the
 *   screen subtree is `inert` (unfocusable, hidden from assistive tech —
 *   its Approve button must never be a real tab stop on a marketing
 *   page); a visually-hidden paragraph narrates the three states
 *   instead, and a visible caption tracks the active state.
 *
 * Reduced-motion detection happens in an effect (client-only, post-
 * mount) rather than in the `useState` initializer — `matchMedia` does
 * not exist during SSR, and branching on it at initializer time is
 * exactly the hydration-mismatch shape `useScrollReveal`'s header
 * comment documents. jsdom without `matchMedia` therefore exercises the
 * full-motion markup by default; tests opt into the reduced path by
 * providing a matching `matchMedia`.
 */
export function HeroDevice() {
  const trackRef = useRef<HTMLDivElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const activeRef = useRef(0);
  const [activeState, setActiveState] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(false);

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      // Same documented hydration-safety pattern as useScrollReveal.ts:
      // this fact is only knowable on the client, one tick past mount.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setReducedMotion(true);
    }
  }, []);

  useEffect(() => {
    if (reducedMotion) return;
    // Non-visual environments (jsdom without pretendToBeVisual) have no
    // rAF — the scrub simply doesn't run there; the markup still renders
    // at its initial state, which is what the tests assert against.
    if (typeof requestAnimationFrame !== "function") return;
    const track = trackRef.current;
    const frame = frameRef.current;
    if (!track || !frame) return;

    let raf = 0;
    let scheduled = false;

    const update = () => {
      scheduled = false;
      const rect = track.getBoundingClientRect();
      const viewport = window.innerHeight || 1;
      const scrollable = Math.max(rect.height - viewport, 1);
      const progress = Math.min(Math.max(-rect.top / scrollable, 0), 1);

      const settle = Math.min(progress / TILT_SETTLE_PROGRESS, 1);
      const eased = 1 - (1 - settle) ** 3;
      const tilt = TILT_MAX_DEG * (1 - eased);
      frame.style.transform = `perspective(1400px) rotateX(${tilt.toFixed(2)}deg)`;

      const index = Math.min(Math.floor(progress * STATE_COUNT), STATE_COUNT - 1);
      if (index !== activeRef.current) {
        activeRef.current = index;
        setActiveState(index);
      }
    };

    const schedule = () => {
      if (!scheduled) {
        scheduled = true;
        raf = requestAnimationFrame(update);
      }
    };

    schedule();
    window.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule, { passive: true });
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
    };
  }, [reducedMotion]);

  const shownState = reducedMotion ? REDUCED_MOTION_STATE : activeState;
  const renderedStates = reducedMotion ? [REDUCED_MOTION_STATE] : [0, 1, 2];

  return (
    <div ref={trackRef} className={styles.track} data-reduced-motion={reducedMotion}>
      <div className={styles.sticky}>
        <div ref={frameRef} className={styles.device} data-testid="hero-device">
          <div className={styles.lid}>
            <span className={styles.camera} aria-hidden="true" />
            {/* Decorative product illustration: real components, but no
                real affordances — inert keeps every control inside the
                screen out of the tab order and the accessibility tree. */}
            <div className={styles.screen} inert>
              {renderedStates.map((index) => (
                <div
                  key={index}
                  className={styles.screenState}
                  data-device-state={index}
                  data-active={index === shownState}
                >
                  <div className={styles.screenBar}>
                    <span className={styles.screenBarBrand}>GharOS</span>
                    <span className={styles.screenBarContext}>
                      {index === 2 ? "Approvals" : "Voice session"}
                    </span>
                  </div>
                  <div
                    className={[styles.screenBody, index === 2 ? styles.screenBodyDense : ""]
                      .filter(Boolean)
                      .join(" ")}
                  >
                    {index === 0 && (
                      <div className={styles.voiceStack}>
                        <SessionStateIndicator state="listening" interrupted={false} />
                        <TranscriptView entries={LANDING_TRANSCRIPT_ENTRIES} />
                      </div>
                    )}
                    {index === 1 && (
                      <ConfirmationPrompt prompt={LANDING_CONFIRMATION_PROMPT} pendingApprovalCount={1} />
                    )}
                    {index === 2 && <ApprovalCard item={LANDING_APPROVAL_ITEM} now={LANDING_APPROVAL_NOW} />}
                  </div>
                </div>
              ))}
            </div>
          </div>
          <div className={styles.deck} aria-hidden="true">
            <span className={styles.scoop} />
          </div>
          <div className={styles.groundShadow} aria-hidden="true" />
        </div>

        <p className={styles.caption} aria-hidden="true">
          <span className={styles.captionIndex}>
            {shownState + 1}&thinsp;/&thinsp;{STATE_COUNT}
          </span>
          {STATE_CAPTIONS[shownState]}
        </p>

        <p className={styles.srOnly}>
          A laptop showing GharOS at work: a spoken request in mixed Hindi and English is transcribed
          with a language tag on every span; the amount is read back in full — ₹3,500, three thousand
          five hundred — and queued rather than paid, because money never moves on voice alone; and the
          payment then waits at the approval gate as an explicit-approval request with its evidence,
          confidence and consequence-if-wrong attached, until a person decides.
        </p>
      </div>
    </div>
  );
}
