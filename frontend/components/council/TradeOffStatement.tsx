import { Badge } from "@/components/design-system/Badge";
import { branchLabel, buildTradeOffStatement, type CouncilBrief } from "@/lib/council";
import styles from "./TradeOffStatement.module.css";

export interface TradeOffStatementProps {
  readonly brief: CouncilBrief;
}

/**
 * The deterministic arbiter's explicit trade-off (spec §12.3 Phase 6),
 * computed prose naming the real winning option and the real people and
 * regret numbers it costs and favours most — never a synthesized
 * consensus paragraph (spec §12.2 design rule 2) and never a verdict this
 * page expects the household to simply accept (spec §12.3 Phase 7: "a
 * decision brief... humans decide").
 */
export function TradeOffStatement({ brief }: TradeOffStatementProps) {
  const statement = buildTradeOffStatement(brief);

  return (
    <section className={styles.panel} aria-label="Explicit trade-off">
      <div className={styles.badgeRow}>
        <Badge variant="royal">Deterministic mechanism, minimax regret</Badge>
        <Badge variant="brass">Brief, not a verdict</Badge>
      </div>

      <p className={styles.winningBranch}>{branchLabel(brief.resolution.winningBranchId)}</p>
      <p className={styles.statement}>{statement}</p>

      <p className={styles.humansDecideNote}>
        This is the Council&apos;s brief, not a decision, the household still weighs it and decides. Nothing on
        this page executes anything, moves money, or places a call.
      </p>
    </section>
  );
}
