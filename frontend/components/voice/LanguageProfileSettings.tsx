"use client";

import { useEffect, useState } from "react";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import {
  fetchLanguageProfile,
  updateLanguageProfile,
  type LanguageProfileOutcome,
} from "@/lib/language-profile";
import { languageDisplayLabel, LITERACY_MODE_DESCRIPTION, LITERACY_MODE_LABEL, LITERACY_MODES, type LanguageProfile, type LiteracyMode } from "@/lib/voice-types";
import { VOICE_HOUSEHOLD_PERSONS } from "@/lib/voice-persons";
import { VoiceprintEnrollment } from "./VoiceprintEnrollment";
import styles from "./LanguageProfileSettings.module.css";

/** Spec §14.2's fixed four-language set. */
const SUPPORTED_LANGUAGE_CODES = ["en", "hi", "mr", "es"] as const;

const SCRIPT_PREFERENCES = ["devanagari", "latin"] as const;

const FORMALITY_OPTIONS = ["informal", "formal"] as const;

/** Local, editable draft of the fields a household member may actually
 * change — `codeMixingProfile` is deliberately absent (spec §14.3:
 * "learned, not declared"). */
interface EditableDraft {
  primaryLanguage: string;
  languagesUnderstood: readonly string[];
  scriptPreference: string;
  formalityPreference: string | null;
  literacyMode: LiteracyMode;
}

function toDraft(profile: LanguageProfile): EditableDraft {
  return {
    primaryLanguage: profile.primaryLanguage,
    languagesUnderstood: profile.languagesUnderstood,
    scriptPreference: profile.scriptPreference,
    formalityPreference: profile.formalityPreference,
    literacyMode: profile.literacyMode,
  };
}

export interface LanguageProfileSettingsProps {
  readonly baseUrl: string;
}

/**
 * Per-person language profile settings (this phase's charter item 4).
 * Real fetch/PATCH against `lib/language-profile.ts` — see that file's
 * own DATA-LOADING BOUNDARY comment for the honest "E3's endpoint may not
 * be live yet" seam this screen renders faithfully rather than papering
 * over with a fixture.
 *
 * `codeMixingProfile` renders read-only (spec §14.3: "learned, not
 * declared") — there is no control anywhere in this form that could edit
 * it, not just a disabled one.
 */
export function LanguageProfileSettings({ baseUrl }: LanguageProfileSettingsProps) {
  const [personId, setPersonId] = useState(VOICE_HOUSEHOLD_PERSONS[0].personId);
  const [loadOutcome, setLoadOutcome] = useState<LanguageProfileOutcome | null>(null);
  const [draft, setDraft] = useState<EditableDraft | null>(null);
  const [codeMixingProfile, setCodeMixingProfile] = useState<string | null>(null);
  const [saveOutcome, setSaveOutcome] = useState<LanguageProfileOutcome | null>(null);
  const [saving, setSaving] = useState(false);

  // Same cancelled-flag + promise-chain shape as `CouncilHistoryBrowser`/
  // `StatusBoard` — every `setState` call lives inside the `.then()`
  // continuation, never synchronously in the effect body itself, so a
  // fast person switch never races a slow one into clobbering state with
  // a stale response (guarded by `cancelled`), and no cascading
  // render-during-effect warning.
  useEffect(() => {
    let cancelled = false;
    fetchLanguageProfile(baseUrl, personId).then((outcome) => {
      if (cancelled) return;
      setLoadOutcome(outcome);
      setSaveOutcome(null);
      if (outcome.status === "success") {
        setDraft(toDraft(outcome.profile));
        setCodeMixingProfile(outcome.profile.codeMixingProfile);
      } else {
        setDraft(null);
      }
    });
    return () => {
      cancelled = true;
    };
  }, [baseUrl, personId]);

  const toggleLanguageUnderstood = (code: string) => {
    setDraft((previous) => {
      if (!previous) return previous;
      const has = previous.languagesUnderstood.includes(code);
      return {
        ...previous,
        languagesUnderstood: has
          ? previous.languagesUnderstood.filter((c) => c !== code)
          : [...previous.languagesUnderstood, code],
      };
    });
  };

  const handleSave = async () => {
    if (!draft) return;
    setSaving(true);
    setSaveOutcome(null);
    const outcome = await updateLanguageProfile(baseUrl, personId, draft);
    setSaveOutcome(outcome);
    setSaving(false);
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.personPicker}>
        <label htmlFor="voice-person-select" className={styles.label}>
          Household member
        </label>
        <select
          id="voice-person-select"
          className={styles.select}
          value={personId}
          onChange={(event) => setPersonId(event.target.value)}
        >
          {VOICE_HOUSEHOLD_PERSONS.map((person) => (
            <option key={person.personId} value={person.personId}>
              {person.displayName}, {person.relationshipToHousehold}
            </option>
          ))}
        </select>
      </div>

      {loadOutcome?.status === "failure" && (
        <p role="alert" className={styles.error}>
          Could not load this person&apos;s language profile: {loadOutcome.message}
          {loadOutcome.httpStatus === 404 && " (the backend language-profile endpoint may not be deployed yet)"}
        </p>
      )}

      {loadOutcome === null && <p className={styles.loading}>Loading language profile…</p>}

      {draft && (
        <Card title="Language profile" className={styles.card}>
          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>Primary language</legend>
            <select
              aria-label="Primary language"
              className={styles.select}
              value={draft.primaryLanguage}
              onChange={(event) => setDraft({ ...draft, primaryLanguage: event.target.value })}
            >
              {SUPPORTED_LANGUAGE_CODES.map((code) => (
                <option key={code} value={code}>
                  {languageDisplayLabel(code)}
                </option>
              ))}
            </select>
          </fieldset>

          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>Languages understood</legend>
            {SUPPORTED_LANGUAGE_CODES.map((code) => (
              <label key={code} className={styles.checkboxLabel}>
                <input
                  type="checkbox"
                  checked={draft.languagesUnderstood.includes(code)}
                  onChange={() => toggleLanguageUnderstood(code)}
                />
                {languageDisplayLabel(code)}
              </label>
            ))}
          </fieldset>

          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>Script preference (for written output)</legend>
            {SCRIPT_PREFERENCES.map((pref) => (
              <label key={pref} className={styles.radioLabel}>
                <input
                  type="radio"
                  name="script-preference"
                  checked={draft.scriptPreference === pref}
                  onChange={() => setDraft({ ...draft, scriptPreference: pref })}
                />
                {pref === "devanagari" ? "Devanagari (देवनागरी)" : "Latin transliteration"}
              </label>
            ))}
          </fieldset>

          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>Formality preference</legend>
            {FORMALITY_OPTIONS.map((option) => (
              <label key={option} className={styles.radioLabel}>
                <input
                  type="radio"
                  name="formality-preference"
                  checked={draft.formalityPreference === option}
                  onChange={() => setDraft({ ...draft, formalityPreference: option })}
                />
                {option === "informal" ? "Informal (tú / tum)" : "Formal (usted / aap)"}
              </label>
            ))}
          </fieldset>

          <fieldset className={styles.fieldset}>
            <legend className={styles.legend}>Literacy mode</legend>
            {LITERACY_MODES.map((mode) => (
              <label key={mode} className={styles.radioLabel}>
                <input
                  type="radio"
                  name="literacy-mode"
                  checked={draft.literacyMode === mode}
                  onChange={() => setDraft({ ...draft, literacyMode: mode })}
                />
                <span>
                  <strong>{LITERACY_MODE_LABEL[mode]}</strong>, {LITERACY_MODE_DESCRIPTION[mode]}
                </span>
              </label>
            ))}
          </fieldset>

          <div className={styles.readOnlyField}>
            <span className={styles.label}>Code-mixing profile (learned, not editable)</span>
            <p className={styles.readOnlyValue}>
              {codeMixingProfile ?? "Not yet observed, this fills in automatically as this person keeps talking to GharOS."}
            </p>
          </div>

          <Button onClick={handleSave} disabled={saving}>
            {saving ? "Saving…" : "Save language profile"}
          </Button>

          {saveOutcome?.status === "success" && (
            <p role="status" className={styles.success}>
              Saved.
            </p>
          )}
          {saveOutcome?.status === "failure" && (
            <p role="alert" className={styles.error}>
              Could not save: {saveOutcome.message}
              {saveOutcome.httpStatus === 404 && " (the backend language-profile endpoint may not be deployed yet)"}
            </p>
          )}
        </Card>
      )}

      <VoiceprintEnrollment baseUrl={baseUrl} personId={personId} />
    </div>
  );
}
