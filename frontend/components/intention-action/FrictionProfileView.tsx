import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { BLOCKER_TYPE_META, patternsForPerson, type FrictionPattern } from "@/lib/intention-action";
import { BLOCKER_TYPE_ICON, BLOCKER_TYPE_VARIANT } from "./blocker-type-visuals";
import styles from "./FrictionProfileView.module.css";

export interface FrictionProfilePerson {
  readonly personId: string;
  readonly displayName: string;
}

export interface FrictionProfileViewProps {
  readonly patterns: readonly FrictionPattern[];
  readonly people: readonly FrictionProfilePerson[];
  /** The id of a pattern just written by a correction this session — given
   * a visible "just updated" treatment so a correction's effect on this
   * view is not just present, but obviously present. */
  readonly justUpdatedPatternId?: string | null;
}

function supportCountLabel(supportCount: number): string {
  return supportCount === 1 ? "seen once" : `seen ${supportCount} times`;
}

/**
 * A real, per-person rendering of each household member's friction profile
 * — every `FrictionPattern` (the TS mirror of a real `Pattern`
 * `CHARACTERIZES`-linked to them), grouped by `BlockerType`, each with its
 * real `supportCount` shown as genuine accumulated evidence, never a
 * certainty (this phase's brief item 2). A person with no pattern on file
 * yet renders an honest empty state, never a fabricated "no issues" claim.
 */
export function FrictionProfileView({ patterns, people, justUpdatedPatternId }: FrictionProfileViewProps) {
  return (
    <div className={styles.grid}>
      {people.map((person) => {
        const own = patternsForPerson(patterns, person.personId);
        return (
          <Card key={person.personId} title={person.displayName} className={styles.card}>
            {own.length === 0 ? (
              <p className={styles.emptyState}>No friction pattern on file yet.</p>
            ) : (
              <ul className={styles.patternList}>
                {own.map((pattern) => {
                  const meta = BLOCKER_TYPE_META[pattern.blockerType];
                  const Icon = BLOCKER_TYPE_ICON[pattern.blockerType];
                  const justUpdated = pattern.id === justUpdatedPatternId;
                  return (
                    <li
                      key={pattern.id}
                      className={[styles.patternRow, justUpdated && styles.justUpdated].filter(Boolean).join(" ")}
                      data-testid={`friction-pattern-${person.personId}-${pattern.blockerType}`}
                    >
                      <div className={styles.patternHeader}>
                        <span className={styles.iconWrap} data-variant={BLOCKER_TYPE_VARIANT[pattern.blockerType]} aria-hidden="true">
                          <Icon size={16} strokeWidth={2} />
                        </span>
                        <Badge variant={BLOCKER_TYPE_VARIANT[pattern.blockerType]}>{meta.label}</Badge>
                        <span className={styles.supportCount}>{supportCountLabel(pattern.supportCount)}</span>
                        {justUpdated && <Badge variant="brass">Just updated</Badge>}
                      </div>
                      <p className={styles.patternDescription}>{pattern.description}</p>
                      <p className={styles.confidenceNote}>
                        {Math.round(pattern.confidence * 100)}% confidence, growing evidence, never treated as
                        certainty from one data point.
                      </p>
                    </li>
                  );
                })}
              </ul>
            )}
          </Card>
        );
      })}
    </div>
  );
}
