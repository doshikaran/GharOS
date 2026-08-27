# The Fair Allocator's fairness guarantee

**Owned jointly by E1 and the CTO (`.claude/agents/e1.md`: "a solver's guarantee in code diverge from what `docs/FAIRNESS_GUARANTEE.md` claims" is a Never-Do). This document is checked word-for-word against `backend/app/solvers/fair_allocation.py` at every Gate 8 review — any gap between the two is an integrity problem, not a wording problem (PHASES.md Phase 8's own CTO review charter).**

Implementation: `backend/app/solvers/fair_allocation.solve_fair_allocation`.
Binding design decision: `docs/adr/014-fair-allocator.md`.
Spec grounding: `GharOS_Build_Spec_v2.md` §8.2.

---

## 1. What property is delivered

**EF1 — envy-free up to one item — for additive cost valuations, computed
by fixed-order round-robin sequential picking.**

This is delivered, in full, by `solve_fair_allocation`. It is **not**
Maximum Nash Welfare, and it is **not** a claim of Pareto-optimality (see
§2). It is the classical, textbook round-robin-picking-sequence result
(Lipton, Markakis, Mossel, Saberi, EC 2004, and the broader
picking-sequences literature), applied to costs instead of values.

### Precise statement

For every pair of people `(A, B)` in one solve, after the algorithm
finishes:

> There exists some single task in A's own bundle such that, if that one
> task were removed, A's remaining cost would be no higher than A's own
> cost for B's entire bundle.

Symbolically, writing `cost_A(S)` for the sum of A's own costs over a set
of tasks `S`, and `bundle_X` for the set of tasks assigned to person X:

```
∃ g ∈ bundle_A  such that  cost_A(bundle_A \ {g}) <= cost_A(bundle_B)
```

Equivalently (since costs are additive, the tightest choice of `g` is A's
own single most expensive task, by A's own valuation):

```
cost_A(bundle_A) - max_{g ∈ bundle_A} cost_A(g)  <=  cost_A(bundle_B)
```

This holds for **every ordered pair** of people after every solve — it is
what `TestEF1ExternalVerification` in
`backend/tests/test_fair_allocation.py` checks directly, independently of
the solver's own internals, on four distinct worked allocations (§4 below
reproduces one by hand).

**Note on which side the removed item comes from.** The standard EF1
definition for *goods* (Caragiannis, Kurokawa, Moulin, Procaccia, Shah,
Wang — EC 2016 / ACM TEAC 2019) removes an item from the **envied**
bundle: the envier's utility for the envied bundle *minus its single
best-to-the-envier item* should not exceed the envier's own utility. For
**chores** (this system's case — cost, not value), the analogous and
correctly-cited definition removes an item from the **envier's own**
bundle instead (Aziz, Caragiannis, Igarashi, Walsh, and the broader
chore-fair-division literature ADR-014 cites): the envier's own cost
*minus its single worst-to-itself item* should not exceed the envier's
cost for the envied bundle. Round-robin picking's classical exchange
argument (§1.1 below) proves exactly this second form. Removing from the
*envied* bundle instead would be a different, stronger, and for chores
*incorrect* claim — this document and the solver both use, and only use,
the correct "remove from the envier's own bundle" form.

### 1.1 Why round-robin delivers this — the exchange argument, in plain language

Fix any two people, A and B, and the fixed pick order the whole solve
uses. Consider every one of A's own turns. On each of those turns, A
looks at everything still unassigned and takes whichever task costs A the
least, among the tasks A is actually capability-eligible for and has a
priced opinion on.

Here is the key fact: at the moment of each of A's turns, any task that B
*eventually* ends up with, and that hadn't been taken by anyone yet, was
just as available to A as it was to B. A had "first refusal" on it and
chose something else instead — something A judged to cost at least as
little. So, task by task, A never picked something more expensive (to A)
than what B later got, whenever both were still on the table.

Lining every one of A's picks up against B's picks in turn order, this
means A's whole bundle costs A no more than B's whole bundle would have
cost A — **except for a possible one-turn offset** caused by whoever
happens to go first in the cycle. That single leftover, unmatched pick is
A's own single most expensive task (by A's own valuation) — remove it,
and the mismatch disappears entirely. That is precisely the EF1 statement
above: A's bundle minus its own worst item is no more costly to A than
B's bundle.

This argument does not care whether "cheaper" means a nicer chore
(inverting to a goods framing) or a less painful one (the chores framing
used here) — the exchange logic is identical either way. That symmetry is
the whole reason a proof that started life for goods carries over to
chores essentially unchanged, and it is why ADR-014 chose this algorithm
specifically: it is a real, textbook, safely-citable result, not an
invented or hoped-for property.

---

## 2. What is explicitly NOT delivered: Pareto-optimality

**Round-robin's output can be Pareto-dominated.** It is possible for
another allocation of the same tasks to exist that leaves every person's
cost the same or lower, with at least one person strictly better off.
`solve_fair_allocation` does not search for such an allocation and makes
no claim to have found the cost-minimal or welfare-maximal split — only
the EF1 fairness property above.

**This is a deliberate, disclosed scope limit, not an oversight.** Spec
§8.2 states the honesty requirement this whole document exists to satisfy:
Maximum Nash Welfare provably gives EF1 **and** Pareto-optimality
simultaneously, but only for allocating *goods* (Caragiannis et al., EC
2016). For *chores* — this system's actual domain, household tasks people
would rather not do — that combined result does not transfer directly:
competitive-equilibrium methods give EF1 + only *fractional*-PO, and only
in "structured cases" (Chaudhury, Garg, McGlaughlin, Mehta, EC 2022); a
general EF1+PO existence result for additive chore costs is recent,
preprint-stage work, not a settled, safely-citable result a household
product should stake a demo claim on.

ADR-014 chose round-robin specifically because its EF1 guarantee for
chores is unconditional and simple enough to state, implement, and verify
completely — rather than reaching for machinery (Maximum Nash Welfare
adapted for costs, or the competitive-equilibrium construction) whose
fairness guarantee for chores is conditional, unresolved, or simply not
yet a settled result. **Overclaiming a mathematical property in front of
judges who know the literature is worse than claiming less** (spec §8.2,
verbatim) — so this document claims exactly EF1, and no more.

A household that wants Pareto-improvements on top of an EF1 allocation
has a real, disclosed path: manual override with reason capture (spec
§8.4's own feature list) — a human can always propose a swap that helps
one person without hurting another; the system does not search for one
automatically.

---

## 3. Capability constraints and the scope of the guarantee

Some tasks are not everyone's to take — a task might need a driving
licence, a working night schedule, or some other real capability. ADR-014
is explicit about how this interacts with the fairness claim: **a person
can only envy a task they could actually have been assigned.** Wanting
something you were never eligible for is not a meaningful notion of envy.

Concretely, `solve_fair_allocation` computes, for every person, a
*solve-feasible* task set: the tasks they are both **capability-eligible**
for and have a **known cost** for. Two people can therefore have entirely
different solve-feasible sets, and the EF1 guarantee above holds with
respect to each person's own valuation *restricted to the tasks they were
actually capability-eligible for* — not some hypothetical unconstrained
world where anyone could do anything.

Capability constraints are enforced **before** the round-robin loop runs
at all, not filtered after an infeasible pick already happened: a task
with zero solve-feasible people anywhere — nobody is both eligible for it
and has a priced opinion on it — is never silently dropped and never
force-assigned to someone incapable or unpriced. It raises
`OrphanedTaskError`, naming the task, so a human sees exactly which task
the matrix cannot yet solve and why (spec §8.6's own failure mode:
"degenerate matrix -> validate before solve; fall back to explicit human
assignment").

---

## 4. Worked example — checkable by hand

Two people, three tasks:

| | `t-1` | `t-2` | `t-3` |
|---|---|---|---|
| **Person 1's cost** | 5 | 5 | 1 |
| **Person 2's cost** | 1 | 1 | 10 |

Both are capability-eligible for, and have priced, all three tasks.
Round-robin order (fixed, lexicographic by id): Person 1, then Person 2.

**Round 0:**
- Person 1's turn — cheapest remaining task for Person 1 is `t-3` (cost 1). Person 1 takes `t-3`.
- Person 2's turn — cheapest remaining task for Person 2, among `{t-1, t-2}`, is a tie at cost 1; the lower task id wins (`t-1` < `t-2`). Person 2 takes `t-1`.

**Round 1:**
- Person 1's turn — only `t-2` remains, cost 5. Person 1 takes `t-2`.
- Person 2's turn — nothing remains; the loop ends.

**Result:** Person 1 = `{t-3, t-2}`, Person 2 = `{t-1}`.

**Checking EF1 by hand:**

- Person 1's own bundle costs Person 1: `1 + 5 = 6`.
- Person 1's cost for Person 2's bundle (`{t-1}`): `5`.
- **Person 1 really does envy Person 2**: `6 > 5`.
- Is it EF1? Remove Person 1's own single most expensive task (`t-2`, cost
  5 to Person 1): `6 - 5 = 1`. Is `1 <= 5`? **Yes.** EF1 holds for this
  pair — the envy is real but resolved by the removal of exactly one
  item.
- Person 2's own bundle costs Person 2: `1`.
- Person 2's cost for Person 1's bundle (`{t-3, t-2}`): `10 + 1 = 11`.
- `1 <= 11`: Person 2 does not envy Person 1 at all — trivially EF1.

Both ordered pairs check out: this allocation is EF1. Note that it is
**not** perfectly envy-free (Person 1 does have real envy before the
one-item relaxation) — that is expected and is exactly the property this
document promises, no more.

This exact scenario is `TestEF1ExternalVerification.test_scenario_a_two_people_bounded_real_envy`
in `backend/tests/test_fair_allocation.py`, checked there by an
independent function that duplicates none of the solver's own internal
logic.

---

## 5. Determinism

Gate 8 requires "identical input -> identical output." `solve_fair_allocation`
has no randomness, no wall-clock dependence, and never depends on
Python's dict/set iteration order: the round-robin order is a single
explicit lexicographic sort of person ids computed once per call, and
every tie-break (equal cost within one person's turn) is broken by task
id, also lexicographic. `TestDeterminism` in
`backend/tests/test_fair_allocation.py` runs the same input twice and
asserts the two `FairAllocationResult`s are equal in full, including the
exact sequence of picks.
