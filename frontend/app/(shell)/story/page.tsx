import type { Metadata } from "next";
import Link from "next/link";
import { Button } from "@/components/design-system/Button";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import { ScrollReveal } from "@/components/landing/ScrollReveal";
import styles from "./home-page.module.css";

export const metadata: Metadata = {
  title: "GharOS — The full story",
  description:
    "An autonomous operating system for the one institution nobody runs like one — built on a knowledge graph that shows its work, not a dashboard that hides it.",
};

/**
 * The full-story page (formerly the landing page at `/`; relocated to
 * `/story` in the 2026-08-29 private-bank pass — the new standalone
 * landing lives in `app/(landing)/`). Kept inside the shell chrome,
 * deliberately absent from the sidebar; the landing's footer links here. Six sections, copy taken close to verbatim from the
 * CTO-frozen brief. Section 3 reuses the real, already-shipped
 * `DerivationBadge` — never a mockup. Section 5's safety-invariant list is
 * pulled verbatim from `PHASES.md` Appendix B (see `SAFETY_INVARIANTS`
 * below), reordered 1-8 by the table's own `#` column for readability;
 * wording is untouched.
 *
 * This page owns the full graph-paper-grid + margin-rule visual identity
 * at full expression (`home-page.module.css`) — the one place the redesign
 * gets to breathe without competing with a dense subsystem UI.
 */

const PAIN_VIGNETTES: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "Fragmented information",
    body: "The budget reality, the care requirements, the school-run logistics, and the resale outlook live in different heads and different documents.",
  },
  {
    title: "Unequal voice",
    body: "Whoever argues hardest or earns most usually wins; quieter members' constraints get discovered after the fact.",
  },
  {
    title: "No memory",
    body: "Two years later, nobody remembers why the choice was made, what was traded away, or who conceded.",
  },
];

const JOURNEY_CHAPTERS: ReadonlyArray<{ name: string; body: string }> = [
  {
    name: "Perception",
    body: "Reads what actually arrives: WhatsApp exports, receipts, SMS, forms — never a hypothetical clean inbox.",
  },
  {
    name: "Consequence Engine",
    body: "Infers what a message actually implies, cites its evidence, and says so plainly when it isn't sure.",
  },
  {
    name: "Arbitration",
    body: "Never moves money or sends a message alone on anything that matters. A human approves first.",
  },
  {
    name: "Household Ledger",
    body: "Finds the leakage hiding in plain sight — a mandate nobody cancelled, a price that quietly crept up.",
  },
  {
    name: "Fair Allocator",
    body: "Divides chores with a provable fairness guarantee, not by whoever complains loudest.",
  },
  {
    name: "Intention → Action",
    body: "Notices when a real plan is quietly stalling, diagnoses why, and does something about it.",
  },
  {
    name: "Outbound Concierge",
    body: "Calls the dentist so you don't have to — and discloses, every time, that it's a system calling.",
  },
  {
    name: "Household Simulator",
    body: "Projects a big decision against your own household's real history, never a stranger's.",
  },
  {
    name: "Household Council",
    body: "Surfaces the real trade-off between real interests. Humans always decide.",
  },
];

const CLOUD_STACK: ReadonlyArray<string> = [
  "Gemini via Vertex AI",
  "Cloud Run",
  "Firestore",
  "Cloud Pub/Sub",
  "Cloud Scheduler",
];

/**
 * Verbatim from `PHASES.md` Appendix B — Safety Invariant Schedule,
 * reordered here by that table's own `#` column (1-8) purely for reading
 * order; the wording in the "Invariant" column is copied exactly, not
 * paraphrased.
 */
const SAFETY_INVARIANTS: ReadonlyArray<string> = [
  "Money reasoners hold no money tools",
  "Audit before execute",
  "Provenance on every node/edge",
  "Low confidence escalates",
  "Financial/irreversible need approval",
  "No debate framing",
  "No fabricated tool success",
  "Voice confers no action capability",
];

export default function Home() {
  return (
    <div className={styles.page}>
      {/* ------------------------------------------------------------ *
       * 1. HERO
       * ------------------------------------------------------------ */}
      <section className={styles.hero}>
        <span className={styles.eyebrow}>GharOS</span>
        <h1 className={styles.heroTitle}>The household remembers, even when you don&rsquo;t.</h1>
        <p className={styles.heroSubtitle}>Not a to-do list. A memory.</p>
        <p className={styles.heroBody}>
          An autonomous operating system for the one institution nobody runs like one — built on a
          knowledge graph that shows its work, not a dashboard that hides it.
        </p>
        <div className={styles.heroActions}>
          <Link href="/graph">
            <Button variant="primary">Enter the graph</Button>
          </Link>
          <Link href="#the-pain">
            <Button variant="secondary">Read how it works</Button>
          </Link>
        </div>
      </section>

      {/* ------------------------------------------------------------ *
       * 2. THE PAIN
       * ------------------------------------------------------------ */}
      <section id="the-pain" className={styles.section}>
        {/* The brief's own "lead line" doubles as this section's heading —
            rendered as an <h2> so the page's heading hierarchy stays
            unbroken (h1 hero -> h2 here -> h3 vignette titles), even
            though visually it reads as a pull-quote, not a typical
            headline. */}
        <h2 className={styles.leadLine}>
          Somewhere between a WhatsApp message about school fees, a crumpled receipt for a water
          purifier, and a doctor&rsquo;s appointment nobody wrote down, the truth of a household gets
          lost.
        </h2>
        <div className={styles.vignetteGrid}>
          {PAIN_VIGNETTES.map((vignette, index) => (
            <ScrollReveal as="article" index={index} key={vignette.title} className={styles.vignette}>
              <h3 className={styles.vignetteTitle}>{vignette.title}</h3>
              <p className={styles.vignetteBody}>{vignette.body}</p>
            </ScrollReveal>
          ))}
        </div>
      </section>

      {/* ------------------------------------------------------------ *
       * 3. THE INSIGHT
       * ------------------------------------------------------------ */}
      <section id="the-insight" className={styles.section}>
        <h2 className={styles.sectionHeadline}>The answer is a path, not a vibe.</h2>
        <p className={styles.sectionBody}>
          Every fact GharOS holds carries how it knows it — extracted from a real document, inferred
          from context, or flagged ambiguous when the evidence genuinely points more than one way. A
          recommendation is never a paragraph asserting itself; it&rsquo;s a subgraph you can walk,
          node by node, back to the message or receipt it came from.
        </p>
        <div className={styles.badgeRow}>
          <DerivationBadge derivation="extracted" />
          <DerivationBadge derivation="inferred" />
          <DerivationBadge derivation="ambiguous" />
        </div>
      </section>

      {/* ------------------------------------------------------------ *
       * 4. THE JOURNEY — nine chapters, scroll-revealed
       * ------------------------------------------------------------ */}
      <section id="the-journey" className={styles.section}>
        <h2 className={styles.sectionHeadline}>The journey</h2>
        <ol className={styles.journeyList} data-testid="journey-list">
          {JOURNEY_CHAPTERS.map((chapter, index) => (
            <ScrollReveal as="li" index={index} key={chapter.name} className={styles.chapter}>
              <span className={styles.chapterNumber} aria-hidden="true">
                {String(index + 1).padStart(2, "0")}
              </span>
              <h3 className={styles.chapterName}>{chapter.name}</h3>
              <p className={styles.chapterBody}>{chapter.body}</p>
            </ScrollReveal>
          ))}
        </ol>
      </section>

      {/* ------------------------------------------------------------ *
       * 5. THE PROOF
       * ------------------------------------------------------------ */}
      <section id="the-proof" className={styles.section}>
        <h2 className={styles.sectionHeadline}>Built on real infrastructure, held to real safety rules.</h2>

        <ul className={styles.stackStrip}>
          {CLOUD_STACK.map((item) => (
            <li key={item} className={styles.stackItem}>
              {item}
            </li>
          ))}
        </ul>

        <ol className={styles.invariantList}>
          {SAFETY_INVARIANTS.map((invariant, index) => (
            <li key={invariant} className={styles.invariantItem}>
              <span className={styles.invariantNumber} aria-hidden="true">
                {index + 1}
              </span>
              {invariant}
            </li>
          ))}
        </ol>
      </section>

      {/* ------------------------------------------------------------ *
       * 6. CLOSING CTA
       * ------------------------------------------------------------ */}
      <section className={styles.closing}>
        <h2 className={styles.closingHeadline}>This isn&rsquo;t a dashboard. It&rsquo;s an institution&rsquo;s memory.</h2>
        <Link href="/graph">
          <Button variant="primary">Enter GharOS</Button>
        </Link>
      </section>
    </div>
  );
}
