import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import { ConfidenceMeter } from "@/components/approvals/ConfidenceMeter";
import { formatDateTime } from "@/lib/approvals";
import type { ConflictingFigure, DisputePresentation } from "@/lib/ledger";
import styles from "./DisputeSurface.module.css";

function formatCurrency(amount: number, currency: string): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, minimumFractionDigits: 2 }).format(amount);
}

/**
 * Renders one `ConflictingFigure`. Deliberately styled identically
 * regardless of which side (`figure_a`/`figure_b`) it is — this component
 * takes no "is this the favoured figure" prop at all, because the point
 * (spec §15.7 A32 forbidden list: "choosing which is correct") is that
 * there is no such thing to encode.
 */
function ConflictingFigureCard({ figure }: { figure: ConflictingFigure }) {
  return (
    <div className={styles.figureCard} data-testid="conflicting-figure">
      <p className={styles.figureSource}>{figure.sourceLabel}</p>
      <p className={styles.figureAmount}>{formatCurrency(figure.amount, figure.currency)}</p>
      <p className={styles.figureMeta}>Reported {formatDateTime(figure.reportedAt)}</p>
      <p className={styles.figureEvidence}>&ldquo;{figure.evidenceText}&rdquo;</p>
      <p className={styles.figureRef}>Evidence: {figure.evidenceEventId}</p>
    </div>
  );
}

export interface DisputeCardProps {
  readonly dispute: DisputePresentation;
}

/**
 * One `DisputePresentation` — both figures shown side by side with equal
 * visual weight, their evidence, the neutral discrepancy amount and
 * context. **There is no resolve/choose affordance anywhere in this
 * component**, matching `DisputePresentation`'s own structural guarantee:
 * the real backend type has no field that could ever hold a chosen
 * figure, and this UI does not editorialise one into existing either.
 */
export function DisputeCard({ dispute }: DisputeCardProps) {
  return (
    <Card className={styles.card} title={dispute.subject}>
      <div className={styles.body}>
        <div className={styles.figures}>
          <ConflictingFigureCard figure={dispute.figureA} />
          <span className={styles.versus} aria-hidden="true">
            vs.
          </span>
          <ConflictingFigureCard figure={dispute.figureB} />
        </div>

        <p className={styles.discrepancy}>
          Discrepancy: <strong>{formatCurrency(dispute.discrepancyAmount, dispute.figureA.currency)}</strong>
        </p>

        <section aria-label="Context">
          <h4 className={styles.sectionLabel}>Context</h4>
          <p className={styles.context}>{dispute.context}</p>
        </section>

        <section aria-label="Confidence">
          <h4 className={styles.sectionLabel}>Confidence</h4>
          <ConfidenceMeter confidence={dispute.confidence} />
        </section>

        <Badge variant="warning">Escalated to human resolution — never auto-resolved</Badge>
      </div>
    </Card>
  );
}

export interface DisputeSurfaceProps {
  readonly disputes: readonly DisputePresentation[];
}

/** A real, browsable list of every open `DisputePresentation` (PHASES.md
 * Phase 7, E4 work item 3 — the dispute UI). */
export function DisputeSurface({ disputes }: DisputeSurfaceProps) {
  if (disputes.length === 0) {
    return <p className={styles.emptyState}>No open disputes right now.</p>;
  }

  return (
    <div className={styles.surface}>
      {disputes.map((dispute) => (
        <DisputeCard key={dispute.subject} dispute={dispute} />
      ))}
    </div>
  );
}
