import { CheckCircle2, Copy, FileWarning, HelpCircle, UserSearch, XCircle, type LucideIcon } from "lucide-react";
import { Badge, type BadgeVariant } from "@/components/design-system/Badge";
import type { DocumentIngestStatus } from "@/lib/connections";
import styles from "./IngestionStatusBadge.module.css";

/**
 * The distinct visual treatment for one `DocumentIngestStatus`
 * (`contracts.ingestion`). Every one of the six outcomes reads
 * differently — icon, wording, badge colour, and a `data-status`
 * attribute the row's own accent border keys off — so a scan result is
 * never an undifferentiated list and a failed extraction is a *visible*
 * failure, never a silent drop (Gate 14.5).
 */
interface StatusPresentation {
  readonly label: string;
  readonly variant: BadgeVariant;
  readonly Icon: LucideIcon;
}

const PRESENTATION: Record<DocumentIngestStatus, StatusPresentation> = {
  ingested: { label: "Added to the graph", variant: "success", Icon: CheckCircle2 },
  duplicate_skipped: { label: "Already seen, skipped", variant: "neutral", Icon: Copy },
  extraction_failed: { label: "Could not read the details", variant: "warning", Icon: FileWarning },
  registry_gap: { label: "Unfamiliar type, sent for review", variant: "info", Icon: HelpCircle },
  entity_resolution_escalated: { label: "Unclear who this refers to, escalated", variant: "warning", Icon: UserSearch },
  error: { label: "Something went wrong", variant: "danger", Icon: XCircle },
};

export function ingestionStatusLabel(status: DocumentIngestStatus): string {
  return PRESENTATION[status].label;
}

export interface IngestionStatusBadgeProps {
  readonly status: DocumentIngestStatus;
}

export function IngestionStatusBadge({ status }: IngestionStatusBadgeProps) {
  const { label, variant, Icon } = PRESENTATION[status];
  return (
    <Badge variant={variant} className={styles.badge} data-status={status}>
      <Icon size={14} aria-hidden="true" className={styles.icon} />
      {label}
    </Badge>
  );
}
