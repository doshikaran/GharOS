import type { Metadata } from "next";
import { LanguageProfileSettings } from "@/components/voice/LanguageProfileSettings";
import { VoiceSessionPanel } from "@/components/voice/VoiceSessionPanel";
import { getApiBaseUrl } from "@/lib/api-base-url";
import styles from "./voice-page.module.css";

export const metadata: Metadata = {
  title: "GharOS, Voice & Multilingual",
};

export default function VoicePage() {
  const baseUrl = getApiBaseUrl();

  return (
    <div className={styles.page}>
      <div className={styles.header}>
        <h1 className={styles.heading}>Voice & Multilingual</h1>
        <p className={styles.subheading}>
          Voice is a first-class input channel on equal footing with email and document upload, it enters the
          same pipeline, produces the same real source documents, and triggers the same subsystems (spec §14.1).
          It is not a chat window with a microphone icon: most of what GharOS does still happens with nobody
          talking to it. This surface exists for the moments someone does, a household member speaking a
          code-mixed sentence, in whichever of English, Hindi, Marathi, or Spanish they reach for mid-sentence
          (spec §14.2), with every consequential read-back requiring an explicit, spoken affirmative before
          anything happens (spec §14.6).
        </p>
      </div>

      <section className={styles.section} aria-label="Live voice session">
        <h2 className={styles.sectionHeading}>Live voice session</h2>
        <VoiceSessionPanel baseUrl={baseUrl} />
      </section>

      <section className={styles.section} aria-label="Per-person language profiles">
        <h2 className={styles.sectionHeading}>Per-person language profiles</h2>
        <p className={styles.sectionIntro}>
          Language is a graph property, not a global setting (spec §14.3), the grandparent who speaks Marathi,
          the parent switching mid-sentence between Hindi and English, the household staff member who may never
          read English, and the child who answers only in English all get addressed the way they actually speak,
          not a single household-wide default.
        </p>
        <LanguageProfileSettings baseUrl={baseUrl} />
      </section>
    </div>
  );
}
