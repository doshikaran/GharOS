"use client";

import { DerivationBadge } from "@/components/design-system/DerivationBadge";
import { Button } from "@/components/design-system/Button";
import type { GraphNode } from "@/lib/graph-types";
import { SourceRegionViewer } from "./SourceRegionViewer";
import styles from "./NodeInspector.module.css";

export interface NodeInspectorProps {
  readonly node: GraphNode;
  readonly baseUrl: string;
  readonly onClose: () => void;
  readonly onExplain: (nodeId: string) => void;
}

function formatFieldKey(key: string): string {
  return key
    .split("_")
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(" ");
}

function formatFieldValue(value: unknown): string {
  if (value === null || value === undefined) return ", ";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

/**
 * Node inspector (Phase 6 item 3): label, type, every `fields` key, and a
 * provenance panel — derivation + confidence rendered via `DerivationBadge`
 * (never a raw number), plus the source region itself, highlighted, when
 * `source_document_id` is set. When it is `null` (a legitimate
 * AMBIGUOUS-derivation case with no single source), this shows that
 * honestly instead of a broken/empty panel.
 */
export function NodeInspector({ node, baseUrl, onClose, onExplain }: NodeInspectorProps) {
  const fieldEntries = Object.entries(node.fields);

  return (
    <aside className={styles.inspector} aria-label="Node inspector">
      <div className={styles.header}>
        <div>
          <p className={styles.type}>{node.type.replace(/_/g, " ")}</p>
          <h3 className={styles.label}>{node.label}</h3>
        </div>
        <button type="button" className={styles.closeButton} onClick={onClose} aria-label="Close node inspector">
          ×
        </button>
      </div>

      <section aria-label="Fields" className={styles.section}>
        <h4 className={styles.sectionHeading}>Fields</h4>
        {fieldEntries.length === 0 ? (
          <p className={styles.emptyNote}>No additional fields recorded on this node.</p>
        ) : (
          <dl className={styles.fieldList}>
            {fieldEntries.map(([key, value]) => (
              <div key={key} className={styles.fieldRow}>
                <dt className={styles.fieldKey}>{formatFieldKey(key)}</dt>
                <dd className={styles.fieldValue}>{formatFieldValue(value)}</dd>
              </div>
            ))}
          </dl>
        )}
      </section>

      <section aria-label="Provenance" className={styles.section}>
        <h4 className={styles.sectionHeading}>Provenance</h4>
        {node.derivation ? (
          <DerivationBadge derivation={node.derivation} confidence={node.confidence ?? undefined} />
        ) : (
          <p className={styles.emptyNote}>No derivation recorded on this node.</p>
        )}

        {node.source_document_id && node.region ? (
          <div className={styles.sourceWrapper}>
            <SourceRegionViewer
              key={node.id}
              baseUrl={baseUrl}
              documentId={node.source_document_id}
              region={node.region}
            />
          </div>
        ) : (
          <p className={styles.emptyNote}>
            No single source document, this node has no one place to point to (expected for an AMBIGUOUS
            derivation drawn from multiple contributing observations).
          </p>
        )}
      </section>

      <Button variant="brass" onClick={() => onExplain(node.id)}>
        Explain this
      </Button>
    </aside>
  );
}
