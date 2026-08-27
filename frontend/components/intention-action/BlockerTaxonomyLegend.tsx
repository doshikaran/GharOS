import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { BLOCKER_TYPES, BLOCKER_TYPE_META, type BlockerType } from "@/lib/intention-action";
import { BLOCKER_TYPE_ICON, BLOCKER_TYPE_VARIANT } from "./blocker-type-visuals";
import styles from "./BlockerTaxonomyLegend.module.css";

export interface BlockerTaxonomyLegendProps {
  /** Highlights one type as "currently diagnosed" — purely visual, used by
   * `IntentionActionExplorer` to tie the legend to whichever diagnosis is
   * on screen. */
  readonly highlighted?: BlockerType;
}

/**
 * spec §9.3 Stage 2's six-type closed taxonomy, made visible and legible —
 * this phase's brief item 3: "the core reasoning step of the whole phase,"
 * rendered with real, distinct visual treatment, not a plain text label.
 */
export function BlockerTaxonomyLegend({ highlighted }: BlockerTaxonomyLegendProps) {
  return (
    <div className={styles.grid}>
      {BLOCKER_TYPES.map((type) => {
        const meta = BLOCKER_TYPE_META[type];
        const Icon = BLOCKER_TYPE_ICON[type];
        const isHighlighted = highlighted === type;
        return (
          <Card
            key={type}
            className={[styles.card, isHighlighted && styles.cardHighlighted].filter(Boolean).join(" ")}
            data-testid={`blocker-type-card-${type}`}
            data-highlighted={isHighlighted}
          >
            <div className={styles.iconRow}>
              <span className={styles.iconWrap} data-variant={BLOCKER_TYPE_VARIANT[type]} aria-hidden="true">
                <Icon size={20} strokeWidth={2} />
              </span>
              <Badge variant={BLOCKER_TYPE_VARIANT[type]}>{meta.label}</Badge>
            </div>
            <p className={styles.description}>{meta.shortDescription}</p>
          </Card>
        );
      })}
    </div>
  );
}
