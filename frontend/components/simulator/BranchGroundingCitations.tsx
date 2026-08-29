import { formatRetrievedAt, type GroundingResult } from "@/lib/simulator";
import styles from "./BranchGroundingCitations.module.css";

export interface BranchGroundingCitationsProps {
  readonly grounding: GroundingResult | undefined;
}

/**
 * A36 Grounding/Research's output for one branch: a real title + a real,
 * clickable link + a retrieval timestamp per citation (this phase's
 * brief — "visibly real-looking, not a bare string"), never truncated,
 * plus the branch-level summary and freshness note.
 *
 * Renders the zero-citation case distinctly and honestly (ADR-017's
 * "honest fallback, never fabricated" rule): when grounding genuinely
 * found nothing, this says so in a clearly-marked callout — it never
 * renders as an empty list that could be mistaken for a loading state or
 * an oversight.
 */
export function BranchGroundingCitations({ grounding }: BranchGroundingCitationsProps) {
  if (!grounding) {
    return (
      <p className={styles.noCitations} role="status">
        No grounding attempted for this branch.
      </p>
    );
  }

  return (
    <div className={styles.wrapper}>
      <p className={styles.summary}>{grounding.summary}</p>

      {grounding.citations.length === 0 ? (
        <p className={styles.noCitations} role="status">
          No external source found, Google Search grounding returned nothing for this branch&apos;s query. Stated
          plainly rather than invented (ADR-017).
        </p>
      ) : (
        <ul className={styles.citationList}>
          {grounding.citations.map((citation) => (
            <li key={citation.uri} className={styles.citation}>
              <a
                href={citation.uri}
                target="_blank"
                rel="noreferrer"
                className={styles.citationTitle}
              >
                {citation.title}
              </a>
              <p className={styles.citationMeta}>
                {citation.uri} · retrieved {formatRetrievedAt(citation.retrievedAt)}
              </p>
            </li>
          ))}
        </ul>
      )}

      <p className={styles.freshnessNote}>{grounding.freshnessNote}</p>
    </div>
  );
}
