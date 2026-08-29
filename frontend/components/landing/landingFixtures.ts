import type { ApprovalQueueItem } from "@/lib/approvals";
import type { ConfirmationPromptEvent } from "@/lib/voice-types";
import type { TranscriptEntry } from "@/components/voice/TranscriptView";

/**
 * Fixture data for the standalone landing page (2026-08-29 private-bank
 * pass) — ONE household transaction, followed end to end: a society
 * maintenance payment of ₹3,500, spoken in code-mixed Hindi/English,
 * read back in full, queued behind the approval gate, approved by a
 * person, written to the ledger.
 *
 * The hero device and the worked-narrative section both draw from this
 * file so the page tells a single continuous story rather than four
 * disconnected screenshots. Names and places match the seeded demo
 * household (`backend/seeds/demo_household.py`: Priya, Sunrise
 * Apartments Society) so the landing reads as the same household a judge
 * later meets inside the app.
 *
 * Fixture-only, marketing-surface data: nothing here is fetched, and no
 * component consuming it implies a live backend. Timestamps are literal
 * ISO strings (never computed off the real clock) so component tests
 * stay deterministic — same convention as `lib/approvals.ts`'s fixture.
 */

/** The code-mixed utterance, tagged per span — never per utterance. */
export const LANDING_TRANSCRIPT_ENTRIES: readonly TranscriptEntry[] = [
  {
    turnId: "landing-turn-1",
    status: "final",
    spans: [
      { text: "Society maintenance", language: "en", confidence: 0.96 },
      { text: "ka payment karna hai", language: "hi", confidence: 0.94 },
    ],
  },
] as const;

/** The read-back register: digit-grouped amount, repeated in words. */
export const LANDING_CONFIRMATION_PROMPT: ConfirmationPromptEvent = {
  type: "confirmation_prompt",
  text: "₹3,500 — three thousand five hundred. Queued for approval — money never moves on voice alone.",
  requiresAffirmative: true,
  turnId: "landing-turn-1",
} as const;

/**
 * Injectable clock for `ApprovalCard`'s `now` prop — a fixed instant
 * before `LANDING_APPROVAL_ITEM.expiresAt`, so the card always renders
 * as genuinely pending (never expired/escalated) no matter when the
 * page is rendered or tested.
 */
export const LANDING_APPROVAL_NOW = new Date("2026-08-22T09:00:00Z");

/** The same payment, arrived at the approval gate: R3, still pending. */
export const LANDING_APPROVAL_ITEM: ApprovalQueueItem = {
  id: "landing-sunrise-maintenance",
  proposedActionSummary:
    "Pay Sunrise Apartments Society's August maintenance of ₹3,500 via the registered mandate.",
  riskTier: "R3",
  confidence: 0.94,
  consequenceIfWrong:
    "A wrong or duplicate payment is an unrecoverable UPI transfer; a missed one risks a late fee from the society.",
  status: "pending",
  expiresAt: "2026-08-23T09:00:00Z",
  evidenceBundle: {
    proposedAction:
      "Pay Sunrise Apartments Society's August maintenance of ₹3,500 via the registered mandate.",
    reasoning:
      "The society's WhatsApp message sets August maintenance at ₹3,500, due by 5 September. The spoken request matches it exactly, and no debit exists yet under this cycle's idempotency key.",
    evidenceConsulted: [
      "WhatsApp message from the Sunrise Apartments Society group, 21 Aug: 'Maintenance for August is ₹3,500, due by 5 September'",
      "Voice request confirmed by read-back: ₹3,500, society maintenance, Priya's registered voice",
      "Ledger check: no existing debit under idempotency key sunrise-society:maintenance:2026-08",
    ],
    confidence: 0.94,
    consequenceIfWrong:
      "A wrong or duplicate payment is an unrecoverable UPI transfer; a missed one risks a late fee from the society.",
  },
} as const;

/** The source message quoted in the worked narrative's first step. */
export const LANDING_SOURCE_MESSAGE = {
  text: "Maintenance for August is ₹3,500, due by 5 September.",
  meta: "Sunrise Apartments Society group · WhatsApp · 21 Aug",
} as const;
