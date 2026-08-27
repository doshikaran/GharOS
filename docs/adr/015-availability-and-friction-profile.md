# ADR-015: DEBT-006 revisited — reuse `Constraint(kind=SCHEDULE)` instead of a new `Person.availability` field; add `characterizes` for friction profiles

**Status:** accepted
**Phase:** 9
**Date:** 2026-08-27

## Context

DEBT-006 (opened Phase 4) recorded that `contracts.graph_types.Person` has no availability field, and named Phase 9's A25 Window Scheduling ("person free AND counterparty open AND historically likely") as the real, spec-named consumer that should drive the field's actual design — deliberately not guessed at in Phase 4, ahead of that real query pattern.

Reaching Phase 9 and examining the real query pattern, plus what already exists in the frozen model, changes the answer DEBT-006's own text assumed. Two things were checked directly before designing anything new:

1. `contracts.graph_types.Constraint` already has `kind: ConstraintKind` including `SCHEDULE`, `severity: ConstraintSeverity` (`HARD`/`SOFT`), and `structured: dict[str, str]` — frozen since Phase 0.
2. `backend/seeds/demo_household.py` already has a real `SCHEDULE`-kind constraint in use (Dadi's nap window, `structured={"quiet_hours": "14:00-16:00"}`, `severity=SOFT`) — an informal, undocumented convention, but proof the mechanism already carries exactly this kind of fact.

That seed example also settles a real semantic question by itself: Dadi's nap window is deliberately **soft** — a preference A25 should route around when it can, not an absolute block. A person's actual working hours (a hard schedule fact — they are physically elsewhere) is a different, **hard** case. This is precisely the distinction a bare `Person.availability` field would have had to reinvent (some kind of severity/priority on each window) — `Constraint.severity` already exists and already means exactly this.

## Decision

**No new `Person.availability` field.** `A25 — Window Scheduling` (E2, this phase) queries `Constraint` nodes of `kind=SCHEDULE` linked to a person via the existing `constrains` edge (frozen since Phase 0): a `HARD` schedule constraint overlapping a candidate window makes that window genuinely unavailable; a `SOFT` one is a window A25 tries to avoid but may use if nothing else fits, exactly matching Dadi's nap-window example's own real-world meaning.

**A formal `structured` key schema for `SCHEDULE`-kind constraints**, replacing the previously-informal, single-example convention (`"quiet_hours"`) with a documented, parseable one E2 builds real parsing/validation code against:

- `days_of_week`: comma-separated lowercase 3-letter days (`"mon,tue,wed,thu,fri"`), or the literal `"daily"` for all seven.
- `start_time` / `end_time`: `"HH:MM"`, 24-hour, local time.

`backend/seeds/demo_household.py`'s existing nap-window entry is migrated to this schema this phase (`structured={"days_of_week": "daily", "start_time": "14:00", "end_time": "16:00"}`) — a deliberate, documented migration of the one entry that predates the formal convention, not a silent break.

**Counterparty (business) availability** — spec's other named input, "counterparty open" — already has a real home: `Provider.availability_notes: str | None`, free text. No structured business-hours field is added for it: A25 is spec-assigned "Flash with Pro-tier fallback" specifically because parsing free-text hours (or resolving an ambiguous case) is exactly what the Pro-tier fallback path is for — matching the tier design already in the roster, not a gap.

**`Obligation.location` (DEBT-006's other named field, for travel-time-aware conflict detection) remains deferred, unaddressed this phase.** Gate 9's checklist has no travel-time requirement — nothing in this phase's real query pattern needs it, so nothing is guessed at. DEBT-006 is split: the availability half is repaid by this ADR; the location half stays open under DEBT-006's original terms (repayment whenever travel-time-aware conflict detection is first demonstrated).

## Decision — the contract addition: `characterizes` edge for friction profiles

Spec §9.4 names a "per-person friction profile" and Gate 9 requires "correction updates the friction profile" — a household member's own history of which blocker types they actually run into, learned over time, correctable when a diagnosis is wrong. `contracts.graph_types.Pattern` ("a mined regularity... a real, general-purpose home for exactly this kind of learned, evidence-backed observation) already exists — but has no edge type connecting a `Pattern` to the specific `PERSON` it characterizes (`Pattern`'s only edge, `learned_from`, points to the `Outcome`s that support it, never to a subject person).

Added `EdgeType.CHARACTERIZES` (`PATTERN -> PERSON`): a person's friction profile is the set of `Pattern` nodes connected to them this way — e.g. "Aarav's dentist-type appointments are blocked by aversion in 4 of 5 recent attempts," `support_count` incrementing as corrections and completions accumulate, exactly matching `Pattern`'s existing design (a mined regularity, never invented from a single data point).

## Alternatives considered

1. **Add `Person.availability` as DEBT-006 originally proposed.** Rejected once the real query pattern was examined: it would have duplicated `Constraint`'s existing hard/soft distinction under a new name, and created two places a person's schedule facts could live (a `Constraint` and an `availability` entry) that could disagree with each other. The disciplined call, per this project's own repeated precedent (ADR-014's `ValuationProfile` design explicitly rejected inventing new shapes for allocation history and concessions once existing mechanisms were found sufficient), is to reuse what already exists rather than duplicate it.
2. **A new node type for friction profiles** (e.g. `FrictionProfile`, one per person). Rejected: `Pattern` already is exactly this concept ("a mined regularity") for every other part of this system (the Fair Allocator's load history, the Simulator's calibration substrate) — a person's blocker tendencies are not a structurally different kind of fact, only a differently-scoped one, and the only real gap was the missing person-linking edge.
3. **Structured business hours on `Provider`.** Rejected: `availability_notes` (free text) plus A25's own spec-assigned Pro-tier fallback tier already covers this; adding a structured field duplicates data a real household's own source documents (a clinic's own posted hours, in whatever format they actually appear) will never arrive in a structured shape anyway.

## Consequences

`EdgeType` now has 36 members (was 35 after ADR-014); `contracts.graph_types` node count is unchanged (18) — this phase adds no new node type. `gharos-graph-model` skill and `.claude/agents/e1.md` updated to reflect the new edge count and the formal `SCHEDULE` `structured` key schema. `docs/DEBT.md`'s DEBT-006 entry is split and updated, not struck outright — the availability half is repaid, the `Obligation.location` half stays open under its original terms.
