import { agentDomainLabel, branchLabel, getCouncilBrief, getCouncilComposition, getSurvivingBranchIds } from "@/lib/council";
import { AdversaryAttackView } from "./AdversaryAttackView";
import { CouncilRiskRegister } from "./CouncilRiskRegister";
import { DelegateScores } from "./DelegateScores";
import { EliminatedBranches } from "./EliminatedBranches";
import { SpecialistPositions } from "./SpecialistPositions";
import { TradeOffStatement } from "./TradeOffStatement";
import styles from "./CouncilExplorer.module.css";

/**
 * Top-level orchestrator for `/council` (PHASES.md Phase 12, ADR-019) — a
 * Server Component (the brief is fixture-backed, same
 * data-loading-boundary discipline `lib/council.ts`'s own module docstring
 * documents; there is nothing to fetch client-side here, unlike
 * `CouncilHistoryBrowser` below it on the page), assembling every Phase 12
 * council component into one coherent view, mirroring
 * `SimulatorExplorer`'s role for `/simulator`.
 *
 * Section order follows the council protocol itself (spec §12.3): who was
 * convened and why, each specialist's independent report, what a hard
 * constraint removed before any scoring happened, each delegate's own
 * conflicting interest, the Adversary's attack on the arbiter's own
 * winning option, the arbiter's explicit trade-off, and the risk register
 * — never a synthesized consensus paragraph anywhere in this sequence.
 *
 * **Humans decide.** Every section here reports evidence or a computed
 * trade-off; nothing in this component tree executes an action, moves
 * money, places a call, or tells the household what to do. See this
 * file's own test for the concrete-phrase check (spec §12.3 Phase 7 /
 * design rule 5 — the Council never makes the final call on an R4-tier
 * decision, it produces a brief).
 */
export function CouncilExplorer() {
  const composition = getCouncilComposition();
  const brief = getCouncilBrief();
  const survivingBranchIds = getSurvivingBranchIds();

  return (
    <div className={styles.explorer}>
      <section className={styles.convening} aria-label="Council convening">
        <p className={styles.question}>{composition.question}</p>
        <p className={styles.trigger}>
          <strong>Trigger — </strong>
          {composition.trigger}
        </p>
        <p className={styles.convened}>
          Convened: {composition.convenedSpecialistIds.map((id) => agentDomainLabel(id)).join("; ")}; delegates for{" "}
          {composition.convenedDelegatePersonIds.length} household members.
        </p>
      </section>

      <section className={styles.humansDecideBanner} role="note" aria-label="Humans decide">
        <strong>Humans decide.</strong> This page reports positions, a computed trade-off, and open risks. It
        never renders a decision the household has already made, and nothing below executes an action, moves
        money, or places a call. The arbiter&apos;s pick is a brief for the family to weigh, not an instruction
        to follow.
      </section>

      <section className={styles.section} aria-label="Specialist positions">
        <h2 className={styles.sectionHeading}>Specialist positions</h2>
        <p className={styles.sectionIntro}>
          Each specialist queried only its own subgraph, independently, before seeing any other agent&apos;s
          output (spec §12.3 Phase 1 — anti-anchoring isolation). Finance reports from real ledger figures;
          Care reports from a real mobility constraint. They are not arguing with each other — they are
          reporting from genuinely different data.
        </p>
        <SpecialistPositions positions={brief.specialistPositions} />
      </section>

      <section className={styles.section} aria-label="Eliminated options">
        <h2 className={styles.sectionHeading}>Eliminated — not scored down</h2>
        <p className={styles.sectionIntro}>
          A hard constraint removes an option from consideration entirely before any interest scoring runs
          (Gate 12: Care&apos;s hard constraint eliminates, it does not score down). What survives below is a
          genuinely different, smaller set — never the same list with a low number attached.
        </p>
        <EliminatedBranches eliminatedBranchIds={brief.resolution.eliminatedBranchIds} positions={brief.specialistPositions} />
        <p className={styles.survivingNote}>
          Surviving options carried into scoring: {survivingBranchIds.map((id) => branchLabel(id)).join(", ")}.
        </p>
      </section>

      <section className={styles.section} aria-label="Delegate scores">
        <h2 className={styles.sectionHeading}>Delegate scores</h2>
        <p className={styles.sectionIntro}>
          Every convened member&apos;s own cost for each surviving option, from their own behaviourally-derived
          valuation profile — genuine conflicting interest, attributed by name, never anonymised into one
          household number.
        </p>
        <DelegateScores delegateScorings={brief.delegateScorings} />
      </section>

      <section className={styles.section} aria-label="Adversary">
        <h2 className={styles.sectionHeading}>The Adversary&apos;s attack</h2>
        <p className={styles.sectionIntro}>
          Structurally tasked with attacking the arbiter&apos;s own winning option (ADR-019 Decision 7) — a
          critique of another agent&apos;s output, rendered distinctly from the positions above, never a sixth
          position among equals.
        </p>
        <AdversaryAttackView attack={brief.adversaryAttack} />
      </section>

      <section className={styles.section} aria-label="Trade-off">
        <h2 className={styles.sectionHeading}>The explicit trade-off</h2>
        <TradeOffStatement brief={brief} />
      </section>

      <section className={styles.section} aria-label="Risk register">
        <h2 className={styles.sectionHeading}>Risk register</h2>
        <CouncilRiskRegister entries={brief.riskRegister} />
      </section>
    </div>
  );
}
