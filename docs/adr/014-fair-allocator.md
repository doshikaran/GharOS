# ADR-014: Fair Allocator — round-robin EF1 solver, `ValuationProfile` node type

**Status:** accepted
**Phase:** 8
**Date:** 2026-08-27

## Context

Spec §8.2 states an explicit "honesty requirement": state precisely which fairness guarantee the implementation delivers, and names the exact literature gap that makes this non-trivial for a household chores allocator — Maximum Nash Welfare (MNW) provably yields EF1 (envy-free up to one item) + Pareto-optimality (PO) for allocating **goods** (Caragiannis et al., EC 2016), but this does **not** transfer directly to allocating **chores** (bads) — competitive-equilibrium methods give EF1 + fractional-PO only in "structured cases" (Chaudhury et al., EC 2022), and a general EF1+PO existence result for additive chore costs is recent, preprint-stage work, not a settled, safely-citable result. Gate 8's own CTO review is explicit: "does the documented guarantee exactly match the code? Any gap is an integrity problem, not a wording problem." This decision has to be made once, correctly, before any code is written — not discovered as a gap during the gate review.

## Decision — the algorithm

**Round-robin sequential picking**, fixed cyclic order over people, each turn the current person takes their least-cost remaining feasible task, repeated until every task is assigned. This is a classical, well-established, symmetric extension of the standard round-robin-for-goods EF1 result (Lipton et al. 2004 and the broader picking-sequences literature): the same exchange argument (at every one of your own turns, you could have taken any task the other person eventually received, and chose one you liked at least as much — i.e. cost at most as much — instead) holds identically whether people are picking their favourite good or their least-bad chore. It is a real, citable, safely-defensible EF1 result for chores under additive cost functions — not an invented or hoped-for property.

**What this explicitly does NOT deliver, stated as plainly as the guarantee itself:** Pareto-optimality. Round-robin can produce a Pareto-dominated allocation (a real, known limitation, not an oversight) — `docs/FAIRNESS_GUARANTEE.md` states this as a limitation, not a footnote.

**Capability constraints, enforced pre-solve (Gate 8's own checklist item):** a task with no feasible person at all raises a typed error naming the orphaned task — it is never silently dropped or force-assigned to an incapable person. When capability constraints restrict some person-task pairs, the EF1 guarantee holds with respect to each person's own valuation of tasks they were actually capability-eligible to receive — envying a task you could never have been assigned in the first place is not a meaningful notion of envy, and `docs/FAIRNESS_GUARANTEE.md` states this precisely rather than silently implying the unconstrained guarantee carries over unexamined.

**Determinism (Gate 8: "identical input → identical output"):** the round-robin order is a fixed, stable sort of person ids (lexicographic) for the duration of one solve call — never adaptive, never reordered mid-solve (adaptive reordering, e.g. "whoever has the lowest cumulative cost so far picks next," is a different, less rigorously provable heuristic and is deliberately not what this implementation does). Ties within one person's turn (multiple remaining tasks at equal cost) break on task id, lexicographic — also fixed and deterministic.

## Decision — the contract addition

Added `ValuationProfile` (`id`, `provenance`, `person_id`, `costs: dict[str, float]`, `elicitation_method`) and `EdgeType.VALUATION_OF` (`VALUATION_PROFILE -> PERSON`) — spec §8.5's "valuation profiles on PERSON" names real graph-write data nothing in the frozen 17-type model could hold (a per-person-per-task cardinal cost matrix is not a `Constraint.structured` bag, and folding it onto `Person` itself would mean an ever-growing, unversioned field on the one node every unrelated part of the system reads for identity/capability lookups — the same reasoning ADR-013 already rejected for attendance data).

**Deliberately not new types:** allocation history and concessions, spec's other two named graph-write targets, already have real homes in the frozen model — no new type invented for either:
- **Allocation history**: an OBLIGATION being reassigned is a real supersession of that OBLIGATION node (the existing node-versioning mechanism, unchanged since Phase 1) carrying a fresh `owned_by` edge — the full historical trail already exists via provenance and superseded-node retention, exactly as it does for every other obligation change in this system.
- **Concessions**: spec's "concession ledger" is already a first-class graph concept — a `DECISION` node with a `CONCEDED_BY` edge to whoever gave ground, exactly what `GraphReader.concession_ledger(person_id)` (frozen since Phase 0) already reads. A Fair Allocator renegotiation where someone accepts a less-preferred share is a `DECISION` like any other in this system, not a special case needing its own type.

## Alternatives considered

1. **Maximum Nash Welfare, adapted for costs** (minimize the product/sum-of-logs of costs). Rejected as the primary solver: spec's own literature review is explicit that MNW's EF1 guarantee does not transfer to chores — shipping it and claiming EF1 anyway would be exactly the overclaim Gate 8's review exists to catch. (A cost-minimizing variant could honestly claim *utilitarian-optimal* or a weaker PO-flavoured property instead of EF1, but round-robin's EF1 is the more legible, more easily-verified-and-explained property for a demo audience, and is what was chosen.)
2. **A general competitive-equilibrium solver** (Chaudhury et al.'s EF1 + fractional-PO construction). Rejected: correct only in "structured cases" per spec's own citation, meaningfully harder to implement and prove correct under real time constraints, and its own paper does not claim unconditional applicability — round-robin's guarantee is unconditional (for additive costs) and far simpler to implement, test exhaustively, and explain.
3. **A new node type for allocation history / concessions.** Rejected once existing mechanisms were checked directly (`GraphReader.concession_ledger` already existed since Phase 0; obligation supersession already existed since Phase 1) — inventing parallel shapes for facts the graph already models would be redundant, not a genuine gap.

## Consequences

`contracts.graph_types` now has 18 node types (was 17) and `EdgeType` now has 35 members (was 34 after ADR-013). `docs/FAIRNESS_GUARANTEE.md` (E1, this phase) is the literal, code-matching statement of exactly what is and is not delivered — EF1 yes, PO no, capability-constrained envy scoped precisely — verified word-for-word against the solver's actual behaviour at this phase's gate, per Gate 8's own review charter. `gharos-graph-model` skill and `.claude/agents/e1.md` updated to reflect the new 18-node/35-edge counts.
