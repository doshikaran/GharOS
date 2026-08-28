import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import type { ProviderRankingResult } from "@/lib/concierge";
import styles from "./RankedShortlist.module.css";

export interface RankedShortlistProps {
  readonly ranking: ProviderRankingResult;
}

const SCORE_COMPONENT_LABEL: Readonly<Record<string, string>> = {
  rating: "Rating",
  distance: "Distance",
  availability: "Availability",
  price: "Price",
  reliability: "Reliability",
};

function scoreComponentEntries(components: Readonly<Record<string, number>>): readonly [string, number][] {
  return Object.entries(components);
}

/**
 * Renders A52's real ranked shortlist (this phase's brief item 2) —
 * every `RankedProvider`'s own `reasons` and `scoreComponents`, never
 * hidden behind the headline `score`. Gate 10's own wording, "the user
 * sees why #1 is #1," is made literal here: #1's card and #2's card are
 * never built from a shared template string — each renders that
 * provider's own real `reasons` array, so a reader can directly compare
 * why one specific provider outranks another specific one, not just that
 * it did. A `demotedForReliability` provider gets an unmissable badge
 * (never a silent lower rank) — Gate 10's own literal test case.
 */
export function RankedShortlist({ ranking }: RankedShortlistProps) {
  if (ranking.ranked.length === 0) {
    return <p className={styles.emptyState}>No providers found for &ldquo;{ranking.serviceCategory}&rdquo; yet.</p>;
  }

  return (
    <div className={styles.wrapper}>
      <div className={styles.header}>
        <Badge variant={ranking.urgency === "elevated" ? "danger" : "neutral"}>
          {ranking.urgency === "elevated" ? "Elevated urgency" : "Routine"}
        </Badge>
        <p className={styles.narrative}>{ranking.narrative}</p>
      </div>

      <ol className={styles.list}>
        {ranking.ranked.map((provider) => (
          <li key={provider.providerId}>
            <Card
              className={styles.card}
              title={
                <span className={styles.titleRow}>
                  <span className={styles.rankBadge} data-rank={provider.rank}>
                    #{provider.rank}
                  </span>
                  <span className={styles.providerName}>{provider.name}</span>
                  <span className={styles.score}>score {provider.score.toFixed(2)}</span>
                  {provider.demotedForReliability && (
                    <Badge variant="danger" data-testid={`demoted-${provider.providerId}`}>
                      Demoted — no-show on file
                    </Badge>
                  )}
                </span>
              }
            >
              <h4 className={styles.sectionLabel}>Why this rank — this provider&apos;s own reasons</h4>
              <ul className={styles.reasonsList}>
                {provider.reasons.map((reason) => (
                  <li key={reason}>{reason}</li>
                ))}
              </ul>

              <h4 className={styles.sectionLabel}>Score breakdown</h4>
              <dl className={styles.componentsGrid}>
                {scoreComponentEntries(provider.scoreComponents).map(([key, value]) => (
                  <div key={key} className={styles.componentRow}>
                    <dt className={styles.componentLabel}>{SCORE_COMPONENT_LABEL[key] ?? key}</dt>
                    <dd className={styles.componentBarTrack}>
                      <span className={styles.componentBarFill} style={{ width: `${Math.round(value * 100)}%` }} />
                    </dd>
                    <span className={styles.componentValue}>{value.toFixed(2)}</span>
                  </div>
                ))}
              </dl>
            </Card>
          </li>
        ))}
      </ol>
    </div>
  );
}
