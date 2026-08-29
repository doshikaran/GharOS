"use client";

import { useState, type FormEvent } from "react";
import { Badge } from "@/components/design-system/Badge";
import { Button } from "@/components/design-system/Button";
import { Card } from "@/components/design-system/Card";
import { BLOCKER_TYPES, BLOCKER_TYPE_META, type BlockerDiagnosis, type BlockerType, type DiagnosisCorrection } from "@/lib/intention-action";
import styles from "./DiagnosisCorrectionForm.module.css";

export interface CorrectionPersonOption {
  readonly personId: string;
  readonly displayName: string;
}

export interface DiagnosisCorrectionFormProps {
  readonly diagnosis: BlockerDiagnosis;
  readonly people: readonly CorrectionPersonOption[];
  readonly onSubmit: (correction: DiagnosisCorrection) => void;
  /** `null` until a correction has been submitted this session — once set,
   * this form renders its confirmation state instead of the form. Owned by
   * the caller (`IntentionActionExplorer`) so the same submitted
   * correction can drive the friction-profile view's update too. */
  readonly submittedCorrection: DiagnosisCorrection | null;
  /** Injectable clock for deterministic tests; defaults to the real time. */
  readonly now?: () => Date;
}

/**
 * A real correction affordance (this phase's brief item 1): pick a
 * different `BlockerType` from the same six-type taxonomy and submit a
 * `correctionNote`. Submitting visibly updates local state (this form's
 * own confirmation, and — via the caller wiring `onSubmit` into
 * `applyDiagnosisCorrection` — the friction profile view, satisfying Gate
 * 9's literal "correction updates the friction profile").
 *
 * **No live write endpoint exists yet this phase** (matching every prior
 * phase's fixture-seam precedent, e.g. `CostMatrix`'s own edit dialog) —
 * this component says so plainly in its own confirmation state rather than
 * implying the correction persisted to the real household graph.
 */
export function DiagnosisCorrectionForm({ diagnosis, people, onSubmit, submittedCorrection, now }: DiagnosisCorrectionFormProps) {
  const clock = now ?? (() => new Date());
  const [correctedType, setCorrectedType] = useState<BlockerType>(diagnosis.blockerType);
  const [correctedBy, setCorrectedBy] = useState<string>(people[0]?.personId ?? "");
  const [note, setNote] = useState("");

  if (submittedCorrection) {
    const correctorName = people.find((p) => p.personId === submittedCorrection.correctedBy)?.displayName ?? submittedCorrection.correctedBy;
    return (
      <Card className={styles.card} title="Correction recorded">
        <div className={styles.confirmationBody} role="status">
          <Badge variant="success">
            Recorded, {BLOCKER_TYPE_META[submittedCorrection.correctedBlockerType].label}
          </Badge>
          <p className={styles.confirmationNote}>
            {correctorName} corrected this diagnosis from{" "}
            <strong>{BLOCKER_TYPE_META[submittedCorrection.originalDiagnosis.blockerType].label}</strong> to{" "}
            <strong>{BLOCKER_TYPE_META[submittedCorrection.correctedBlockerType].label}</strong>: &ldquo;
            {submittedCorrection.correctionNote}&rdquo;
          </p>
          <p className={styles.caveat}>
            Recorded locally for this session only, there is no live write endpoint yet to persist this correction
            back to the household graph. The friction profile below reflects it for this session.
          </p>
        </div>
      </Card>
    );
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmedNote = note.trim();
    if (trimmedNote.length === 0 || correctedBy.length === 0) return;
    onSubmit({
      obligationId: diagnosis.obligationId,
      personId: diagnosis.personId,
      originalDiagnosis: diagnosis,
      correctedBlockerType: correctedType,
      correctionNote: trimmedNote,
      correctedBy,
      correctedAt: clock().toISOString(),
    });
  }

  return (
    <Card className={styles.card} title="Disagree with this diagnosis?">
      <form className={styles.form} onSubmit={handleSubmit}>
        <p className={styles.intro}>
          Pick the blocker type this actually is, and explain why, the correction is recorded against this
          person&apos;s friction profile, the same real evidence a future diagnosis will weigh.
        </p>

        <label className={styles.field}>
          <span className={styles.fieldLabel}>Actual blocker type</span>
          <select
            className={styles.select}
            value={correctedType}
            onChange={(event) => setCorrectedType(event.target.value as BlockerType)}
            aria-label="Actual blocker type"
          >
            {BLOCKER_TYPES.map((type) => (
              <option key={type} value={type}>
                {BLOCKER_TYPE_META[type].label}
                {type === diagnosis.blockerType ? " (originally diagnosed)" : ""}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.fieldLabel}>Corrected by</span>
          <select
            className={styles.select}
            value={correctedBy}
            onChange={(event) => setCorrectedBy(event.target.value)}
            aria-label="Corrected by"
          >
            {people.map((person) => (
              <option key={person.personId} value={person.personId}>
                {person.displayName}
              </option>
            ))}
          </select>
        </label>

        <label className={styles.field}>
          <span className={styles.fieldLabel}>Why?</span>
          <textarea
            className={styles.textarea}
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder="Explain what the real blocker actually is, in your own words…"
            aria-label="Correction note"
            rows={3}
          />
        </label>

        <Button type="submit" variant="brass" disabled={note.trim().length === 0}>
          Submit correction
        </Button>
      </form>
    </Card>
  );
}
