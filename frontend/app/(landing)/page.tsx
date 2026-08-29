import type { Metadata } from "next";
import Link from "next/link";
import { EvidenceBundleView } from "@/components/approvals/EvidenceBundleView";
import { RiskTierBadge } from "@/components/approvals/RiskTierBadge";
import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import { HeroDevice } from "@/components/landing/HeroDevice";
import { ScrollReveal } from "@/components/landing/ScrollReveal";
import {
  LANDING_APPROVAL_ITEM,
  LANDING_SOURCE_MESSAGE,
} from "@/components/landing/landingFixtures";
import styles from "./landing-page.module.css";

export const metadata: Metadata = {
  title: "GharOS — The household remembers, even when you don't",
  description:
    "GharOS reads the messages, receipts and voice notes a household actually produces, remembers what they imply, and never moves money without a person saying yes.",
};

/**
 * The standalone landing at `/` (2026-08-29 private-bank pass,
 * operator-frozen plan). One narrow reading spine on a near-monochrome
 * ground; champagne appears in exactly five places (two CTAs, the
 * read-back amount, one rule, the footer mark). One transaction —
 * ₹3,500 society maintenance — threads through the hero device and the
 * worked narrative, rendered with the REAL product components
 * (`components/landing/landingFixtures.ts`), never mockups.
 *
 * Motion budget (a ceiling, from the plan): the staged hero load
 * reveal, the scroll-scrubbed device, and uniform once-only section
 * reveals — nothing else. Everything animates on transform/opacity
 * only, and the page composes fully statically under
 * prefers-reduced-motion.
 */

const ARRIVES_ITEMS: ReadonlyArray<{ title: string; body: string }> = [
  {
    title: "WhatsApp exports",
    body: "Society notices, school threads, vendor confirmations — the group chats where household truth actually lives.",
  },
  {
    title: "Receipts and SMS",
    body: "Crumpled paper photographed on the kitchen table, bank alerts, a handwritten payroll register.",
  },
  {
    title: "Voice in four languages",
    body: "English, Hindi, Marathi and Spanish — often inside the same sentence.",
  },
];

const NEVER_LINES: ReadonlyArray<string> = [
  "Money reasoners hold no money tools.",
  "Nothing sends without approval.",
  "Voice alone never moves money.",
  "Every fact shows its source.",
];

const PROOF_LINE = "Gemini via Vertex AI · Cloud Run · Firestore · Pub/Sub · Cloud Scheduler";

export default function Landing() {
  return (
    <div className={styles.page}>
      {/* ------------------------------------------------------------ *
       * 1 + 2. HERO, then the device — staged load reveal (one easing,
       * four steps, done inside 1.2s), then the scroll-scrubbed laptop.
       * ------------------------------------------------------------ */}
      <section className={styles.hero} aria-labelledby="hero-title">
        <h1 id="hero-title" className={`${styles.heroTitle} ${styles.loadStep1}`}>
          The household remembers, even when you don&rsquo;t.
        </h1>
        <p className={`${styles.heroSub} ${styles.loadStep2}`}>
          GharOS reads the messages, receipts and voice notes your household already produces — and
          asks before anything real happens.
        </p>
        <div className={`${styles.heroCta} ${styles.loadStep3}`}>
          {/* A link styled as the brass button (not design-system Button,
              which renders a real <button> — nesting that inside a Link is
              invalid interactive-inside-interactive markup). */}
          <Link href="/graph" className={styles.ctaButton}>
            Get started
          </Link>
        </div>
        <div className={styles.loadStep4}>
          <HeroDevice />
        </div>
      </section>

      {/* ------------------------------------------------------------ *
       * 3. WHAT IT RUNS ON — three quiet items.
       * ------------------------------------------------------------ */}
      <section className={styles.section} aria-labelledby="arrives-title">
        <ScrollReveal>
          <h2 id="arrives-title" className={styles.sectionTitle}>
            It runs on what actually arrives
          </h2>
        </ScrollReveal>
        <dl className={styles.arrivesList}>
          {ARRIVES_ITEMS.map((item, index) => (
            <ScrollReveal as="div" index={index + 1} key={item.title} className={styles.arrivesItem}>
              <dt className={styles.arrivesTitle}>{item.title}</dt>
              <dd className={styles.arrivesBody}>{item.body}</dd>
            </ScrollReveal>
          ))}
        </dl>
      </section>

      {/* ------------------------------------------------------------ *
       * 4. WORKED NARRATIVE — the same ₹3,500, end to end.
       * ------------------------------------------------------------ */}
      <section className={styles.section} aria-labelledby="narrative-title">
        <ScrollReveal>
          <h2 id="narrative-title" className={styles.sectionTitle}>
            One payment, end to end
          </h2>
          <p className={styles.sectionLead}>
            The same request from the screen above, followed all the way through.
          </p>
        </ScrollReveal>

        <ol className={styles.steps} data-testid="worked-narrative">
          <ScrollReveal as="li" index={1} className={styles.step}>
            <h3 className={styles.stepTitle}>A message arrives</h3>
            <blockquote className={styles.sourceMessage}>
              <p className={styles.sourceMessageText}>&ldquo;{LANDING_SOURCE_MESSAGE.text}&rdquo;</p>
              <footer className={styles.sourceMessageMeta}>{LANDING_SOURCE_MESSAGE.meta}</footer>
            </blockquote>
          </ScrollReveal>

          <ScrollReveal as="li" index={2} className={styles.step}>
            <h3 className={styles.stepTitle}>An obligation is inferred</h3>
            <div className={styles.obligation}>
              <div className={styles.obligationHead}>
                <DerivationBadge derivation="inferred" />
                <span className={styles.obligationAmount}>₹3,500</span>
                <span className={styles.obligationDue}>due 5 Sep 2026</span>
              </div>
              <p className={styles.stepBody}>
                Not stated as a task anywhere — implied by the message, and recorded with the evidence
                that implies it:
              </p>
              <ul className={styles.evidenceQuotes}>
                <li>{LANDING_APPROVAL_ITEM.evidenceBundle.evidenceConsulted[0]}</li>
              </ul>
            </div>
          </ScrollReveal>

          <ScrollReveal as="li" index={3} className={styles.step}>
            <h3 className={styles.stepTitle}>Queued for approval</h3>
            <p className={styles.stepBody}>
              Any movement of money waits here, with everything a person needs to decide:
            </p>
            <div className={styles.bundleCard}>
              <RiskTierBadge tier={LANDING_APPROVAL_ITEM.riskTier} />
              <EvidenceBundleView bundle={LANDING_APPROVAL_ITEM.evidenceBundle} />
            </div>
          </ScrollReveal>

          <ScrollReveal as="li" index={4} className={styles.step}>
            <h3 className={styles.stepTitle}>Approved by a person</h3>
            {/* The one place on this page the ledger's red margin rule may
                appear — inside the ledger card, quoting the product. */}
            <div className={styles.ledgerCard}>
              <div className={styles.ledgerRow}>
                <span className={styles.ledgerDate}>05 Sep 2026</span>
                <span className={styles.ledgerParty}>Sunrise Apartments Society · maintenance</span>
                <span className={styles.ledgerAmount}>&minus;&thinsp;₹3,500</span>
              </div>
              <p className={styles.ledgerNote}>
                Approved by Priya · ledger entry written · traceable back to the message it came from.
              </p>
            </div>
          </ScrollReveal>
        </ol>
      </section>

      {/* ------------------------------------------------------------ *
       * 5. WHAT IT WILL NEVER DO — restraint as the luxury.
       * ------------------------------------------------------------ */}
      <section className={styles.section} aria-labelledby="never-title">
        <ScrollReveal>
          <span className={styles.neverRule} aria-hidden="true" />
          <h2 id="never-title" className={styles.sectionTitle}>
            What it will never do
          </h2>
        </ScrollReveal>
        <ul className={styles.neverList}>
          {NEVER_LINES.map((line, index) => (
            <ScrollReveal as="li" index={index + 1} key={line} className={styles.neverItem}>
              {line}
            </ScrollReveal>
          ))}
        </ul>
      </section>

      {/* ------------------------------------------------------------ *
       * 6. PROOF LINE, CLOSING CTA, FOOTER.
       * ------------------------------------------------------------ */}
      <section className={styles.closing} aria-labelledby="closing-title">
        <ScrollReveal>
          <p className={styles.proofLine}>{PROOF_LINE}</p>
          <h2 id="closing-title" className={styles.closingTitle}>
            Ready before the next message arrives.
          </h2>
          <Link href="/graph" className={styles.ctaButton}>
            Get started
          </Link>
        </ScrollReveal>
      </section>

      <footer className={styles.footer}>
        <span className={styles.footerMark}>GharOS</span>
        <Link href="/story" className={styles.footerLink}>
          The full story &rarr;
        </Link>
      </footer>
    </div>
  );
}
