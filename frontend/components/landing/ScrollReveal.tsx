"use client";

import type { ElementType, ReactNode } from "react";
import { useScrollReveal } from "./useScrollReveal";
import styles from "./ScrollReveal.module.css";

export interface ScrollRevealProps {
  children: ReactNode;
  /** Stagger position within a revealed group (0-based) — each step adds
   * one more `--reveal-stagger` of transition-delay, so a sequence of
   * chapters cascades in rather than arriving all at once. */
  index?: number;
  /** Rendered tag — a `<section>`/`<li>`/`<div>` etc, per call site. */
  as?: ElementType;
  className?: string;
}

/**
 * Reusable scroll-reveal wrapper for the landing page's staggered chapter
 * animation (`docs/design/2026-08-29-redesign-brief.md`) — thin JSX shell
 * around `useScrollReveal`. Marketing/landing surfaces only: this is what
 * the new `--reveal-*` tokens exist for; ordinary product UI keeps using
 * the existing `--motion-*` tokens and stays un-animated by default.
 */
export function ScrollReveal({ children, index = 0, as: Tag = "div", className }: ScrollRevealProps) {
  const { ref, visible } = useScrollReveal<HTMLElement>();

  return (
    <Tag
      ref={ref}
      className={[styles.reveal, className].filter(Boolean).join(" ")}
      data-visible={visible}
      style={{ transitionDelay: `calc(${index} * var(--reveal-stagger))` }}
    >
      {children}
    </Tag>
  );
}
