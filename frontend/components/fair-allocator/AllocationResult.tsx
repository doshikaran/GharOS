import { Badge } from "@/components/design-system/Badge";
import { Card } from "@/components/design-system/Card";
import type { EF1Violation, FairAllocationResult } from "@/lib/fair-allocator";
import styles from "./AllocationResult.module.css";

export interface AllocationResultProps {
  readonly result: FairAllocationResult;
  readonly violations: readonly EF1Violation[];
  readonly taskTitle: (taskId: string) => string;
  readonly personName: (personId: string) => string;
  readonly heading?: string;
}

function formatCost(cost: number): string {
  return cost.toFixed(1);
}

/**
 * Renders one real `solve_fair_allocation` output — the deterministic
 * solver's full pick trail, each person's bundle, and the **envy-free up
 * to one item (EF1)** verification, using the term precisely (spec §8.2's
 * own honesty requirement; `docs/FAIRNESS_GUARANTEE.md` §1-§2). Never says
 * "optimal" or an unqualified "fair" — EF1 is explicitly *not* a claim of
 * Pareto-optimality, and this component's copy never implies otherwise.
 */
export function AllocationResult({ result, violations, taskTitle, personName, heading }: AllocationResultProps) {
  const ef1Holds = violations.length === 0;

  return (
    <div className={styles.wrapper}>
      {heading && <h3 className={styles.heading}>{heading}</h3>}

      <Card title="Fairness property verified">
        <div className={styles.ef1Row}>
          <Badge variant={ef1Holds ? "success" : "danger"}>
            {ef1Holds ? "Envy-free up to one item (EF1) — holds" : "EF1 violation found"}
          </Badge>
          <p className={styles.ef1Gloss}>
            In plain terms: for every pair of people, there is at least one task in the first person&apos;s own share
            that, if set aside, would make their remaining share cost them no more than the other person&apos;s whole
            share would. This is a deterministic, computed check (<code>verify_ef1</code>) — not a model&apos;s
            opinion, and it does not claim there is no cheaper way to split these same tasks across everyone at once;
            it is exactly this one, named property, no more (see <code>docs/FAIRNESS_GUARANTEE.md</code>).
          </p>
        </div>
        {ef1Holds ? (
          <p className={styles.ef1Empty}>
            <code>verify_ef1</code> returned zero violations across every ordered pair of people in this solve.
          </p>
        ) : (
          <ul className={styles.violationList}>
            {violations.map((violation) => (
              <li key={`${violation.envier}-${violation.envied}`}>
                {personName(violation.envier)} envies {personName(violation.envied)}: their own bundle costs them{" "}
                {formatCost(violation.envierOwnBundleCost)}, and even after removing their costliest task (
                {formatCost(violation.envierWorstOwnItemCost)}) it still exceeds their own cost for the other
                person&apos;s bundle ({formatCost(violation.envierCostForEnviedBundle)}).
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card title="Each person's share">
        <div className={styles.bundles}>
          {result.order.map((personId) => {
            const taskIds = Object.entries(result.allocation)
              .filter(([, owner]) => owner === personId)
              .map(([taskId]) => taskId);
            return (
              <div key={personId} className={styles.bundleCard}>
                <h4 className={styles.bundlePerson}>{personName(personId)}</h4>
                {taskIds.length === 0 ? (
                  <p className={styles.noTasks}>No tasks this cycle.</p>
                ) : (
                  <ul className={styles.taskList}>
                    {taskIds.map((taskId) => (
                      <li key={taskId}>{taskTitle(taskId)}</li>
                    ))}
                  </ul>
                )}
                <p className={styles.bundleTotal}>
                  Total cost to {personName(personId)}: <strong>{formatCost(result.personTotalCost[personId] ?? 0)}</strong>
                </p>
              </div>
            );
          })}
        </div>
      </Card>

      <Card title="The solver's pick trail">
        <div className={styles.tableScroll}>
          <table className={styles.picksTable}>
            <thead>
              <tr>
                <th scope="col">Turn</th>
                <th scope="col">Round</th>
                <th scope="col">Person</th>
                <th scope="col">Task taken</th>
                <th scope="col">Cost to them</th>
              </tr>
            </thead>
            <tbody>
              {result.picks.map((pick) => (
                <tr key={pick.turnIndex}>
                  <td>{pick.turnIndex}</td>
                  <td>{pick.roundNumber}</td>
                  <td>{personName(pick.personId)}</td>
                  <td>{taskTitle(pick.taskId)}</td>
                  <td>{formatCost(pick.cost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className={styles.order}>Fixed pick order this solve: {result.order.map(personName).join(" → ")}</p>
      </Card>
    </div>
  );
}
