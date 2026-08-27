import { NODE_TYPES, type NodeType } from "@/lib/graph-types";
import { EDGE_DERIVATION_VISUALS, NODE_VISUALS } from "@/lib/graph-visual-encoding";
import { NodeGeometryIcon } from "./NodeGeometryIcon";
import styles from "./GraphLegend.module.css";

const NODE_TYPE_LABELS: Record<NodeType, string> = {
  PERSON: "Person",
  CONSTRAINT: "Constraint",
  OBLIGATION: "Obligation",
  LEDGER_EVENT: "Ledger event",
  RECURRING_COMMITMENT: "Recurring commitment",
  VENDOR: "Vendor",
  PROVIDER: "Provider",
  DECISION: "Decision",
  BRANCH: "Branch",
  COUNCIL_POSITION: "Council position",
  OUTCOME: "Outcome",
  SOURCE_DOCUMENT: "Source document",
  ACTION_RECORD: "Action record",
  APPROVAL_REQUEST: "Approval request",
  PURCHASE_ITEM: "Purchase item",
  PATTERN: "Pattern",
  ATTENDANCE_RECORD: "Attendance record",
  VALUATION_PROFILE: "Valuation profile",
};

/**
 * The at-a-glance key for the graph canvas's visual encoding (Phase 6 item
 * 1: "16 types need to stay visually distinguishable — use shape or icon
 * plus color, not color alone"). Every node type gets its own icon here so
 * a judge (or a household member) can learn the convention once and read
 * it correctly straight off the canvas, the same way `DerivationBadge`
 * teaches the edge-style convention.
 */
export function GraphLegend() {
  return (
    <div className={styles.legend} aria-label="Graph legend">
      <section>
        <h3 className={styles.heading}>Node types</h3>
        <ul className={styles.nodeGrid}>
          {NODE_TYPES.map((type) => {
            const visual = NODE_VISUALS[type];
            return (
              <li key={type} className={styles.nodeEntry}>
                <NodeGeometryIcon geometry={visual.geometry} fillMode={visual.fillMode} colorToken={visual.colorToken} />
                <span>{NODE_TYPE_LABELS[type]}</span>
              </li>
            );
          })}
        </ul>
      </section>

      <section>
        <h3 className={styles.heading}>Edge derivation</h3>
        <ul className={styles.edgeList}>
          {(Object.keys(EDGE_DERIVATION_VISUALS) as Array<keyof typeof EDGE_DERIVATION_VISUALS>).map((derivation) => {
            const visual = EDGE_DERIVATION_VISUALS[derivation];
            const dashArray = visual.dash.join(",");
            return (
              <li key={derivation} className={styles.edgeEntry}>
                <svg width="36" height="12" viewBox="0 0 36 12" aria-hidden="true">
                  <line
                    x1={2}
                    y1={6}
                    x2={34}
                    y2={6}
                    stroke={`var(${visual.colorToken})`}
                    strokeWidth={2.5}
                    strokeDasharray={dashArray.length > 0 ? dashArray : undefined}
                  />
                </svg>
                <span>{derivation[0].toUpperCase() + derivation.slice(1)}</span>
              </li>
            );
          })}
          <li className={styles.edgeEntry}>
            <svg width="36" height="12" viewBox="0 0 36 12" aria-hidden="true">
              <line x1={2} y1={6} x2={34} y2={6} stroke="var(--edge-conflict)" strokeWidth={4.5} />
            </svg>
            <span>Conflict</span>
          </li>
        </ul>
      </section>
    </div>
  );
}
