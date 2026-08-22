---
name: gharos-gate-review
description: Use when a GharOS phase's work items are complete and its Green-Light Gate needs to be run, when acting as cto reviewing E1-E4 output, when writing an ADR (Architecture Decision Record) for a GharOS decision, or when writing the phase summary into verification.md.
---

# GharOS phase gate review

Full source: `PHASES.md` §0.2, and each phase's own `🟢 GATE N` checklist plus its "CTO review:" prompt — always re-read the specific phase's gate section directly, this skill is the *process*, not a substitute for the phase-specific checklist.

## The rule that matters most

**Phases are gated, not sequential-by-default.** A phase is complete only when its gate passes in full. If a gate item fails, fix it *inside that phase*. Never carry a failing gate item forward as "we'll fix it later" — that is exactly the technical debt PHASES.md exists to prevent. The one narrow exception is a shortcut explicitly approved by the CTO and logged in `docs/DEBT.md` with an owner and a repayment phase.

**The operator's standing instruction on top of this:** run exactly one phase at a time. Do not dispatch or plan work for the next phase while the current one is open. At gate time, write the phase summary to `verification.md` and stop — wait for the operator's explicit instruction before starting the next phase.

## How to run a gate review (as cto)

1. Re-read the phase's own `🟢 GATE N` section in `PHASES.md` verbatim — do not review from memory.
2. Walk every checklist item and verify it directly rather than trusting a report:
   - For a "proven by test" item — find the test, read it, confirm it actually exercises the claim (not a trivial assertion like `assert True` or a mock that always succeeds).
   - For a "no X exists" item (e.g. no Dockerfile, no debate framing) — run the actual search yourself: `find . -iname "Dockerfile*"`, `grep -rni "debate" --include="*.py" --include="*.ts" --include="*.tsx" --include="*.md" .` (excluding this skill file and the spec/phases docs themselves, which reference the word only to forbid it).
   - For a "personally inspect" item (several gates literally say this — e.g. Gate 7's "inspect A28's registered tools directly", Gate 12's "if two specialists were swapped, would output change?") — do that inspection yourself, don't accept a summary from the engineer who built it.
3. Check `contracts/` still matches the implementation — a drift here is a defect even if tests pass, because contract tests are supposed to catch it; if they didn't, the contract tests are also a gap worth flagging.
4. Check `docs/DEBT.md` for any new entries — every one needs your explicit approval or it's a fail.
5. Confirm the eight safety invariants relevant to this phase (see the invariant-schedule table in `gharos-standards`) are real, passing tests — not placeholders, unless the phase's own gate explicitly allows a placeholder.
6. Only sign the gate when every item passes. A partial pass is not a pass — there is no "mostly done" state for a gate.

## Writing the phase summary into `verification.md`

`verification.md` lives at the repo root, is append-only (never rewrite a prior phase's section — if something about a signed phase later turns out wrong, add a note under the *current* phase's section referencing it, don't edit history), and gets one section per phase in this shape:

```markdown
## Phase N — <name>

**Gated:** YYYY-MM-DD
**Roles active:** <e.g. cto (lead), e1, e3, e4>

### What was built
<concrete, specific list — files/modules, not vague claims>

### Gate checklist result
<walk the phase's own PHASES.md gate items one by one, ✅/❌ with a one-line note per item — not just "all passed">

### Verified personally (not just reported)
<the specific things the CTO checked directly, per the "personally inspect" instruction above, and what was found>

### Decisions / ADRs
<links to any new docs/adr/NNN files this phase produced>

### Debt / deferred items
<anything in docs/DEBT.md from this phase, with owner and repayment phase — or "none">

### Open items for the operator
<anything that needs a human decision before the next phase can safely start>
```

Keep it factual and specific — this file is what the operator reads to decide whether to authorise the next phase, so vague "everything looks good" summaries defeat its purpose.

## Writing an ADR

One ADR per non-obvious decision (PHASES.md §7 requires this at every phase). Keep it short:

```markdown
# ADR-NNN: <decision title>

**Status:** accepted
**Phase:** <N>
**Date:** <YYYY-MM-DD>

## Context
<the problem/tension that forced a decision>

## Decision
<what was chosen>

## Alternatives considered
<what else was on the table, and why it lost>

## Consequences
<what this makes easier, what it makes harder, what it forecloses>
```

Store under `docs/adr/NNN-short-title.md`, sequential numbering. Known ADR-worthy decisions already flagged in PHASES.md: Firestore layout for edges (Phase 0/1, done — ADR-001), Result-vs-exception policy (Phase 0, done — ADR-002), prompt versioning (Phase 0, done — ADR-003), Firestore composite indexes vs. a future graph-native store (Phase 1, revisit if traversal perf is a problem), D3 vs Cytoscape.js (Phase 6, only if switched).

## Track-eligibility check — run this at every gate, not just at the end

GharOS must keep presenting as ONE household agent with specialized sub-agents — never a fleet of independent institutional agents (spec §3.1). At every gate, ask: did anything built this phase introduce an agent registry, cross-household discovery, or multi-tenant governance? If yes, that is a gate failure regardless of what else passed.

## Per-phase gate quick-reference (the specific "personally verify" instructions from PHASES.md — always cross-check against the live section, this list is a memory aid, not authoritative)

- **Gate 0:** contracts import cleanly with zero Firestore/FastAPI leakage; six diagrams committed; `/tokens` renders correctly both themes; emulators run locally; budget alert active; no Dockerfile; lint/types clean both sides.
- **Gate 1:** every node/edge type round-trips; a provenance-less write is impossible (hypothesis fuzz test); all 14 traversals tested; `unexplained(scope)` empty on seeded graph; audit precedes side effects (proven by test); same idempotency key twice → one effect; integrity checker clean.
- **Gate 2:** all three mandatory Google Cloud requirements screenshotted from *deployed* form; scheduler→pubsub→cloud run round trip unattended; `min-instances=0` confirmed via `gcloud run services describe`; no Dockerfile; Pro-tier allowlist enforced by a failing test on violation.
- **Gate 3:** 20+ golden documents across 8+ registry types extract correctly; every field has a source-region pointer; below-floor attendance register surfaces the image; a receipt produces correct LEDGER_EVENT + PURCHASE_ITEM edges; planted mismatch → contradicts edge + escalation, no overwrite; unknown type → logged registry gap; extraction and implication are provably separate agents.
- **Gate 4:** canonical field-trip email → ≥5 implied obligations with valid citations; every implied obligation has a verified source span; uncitable inferences discarded (adversarial test); hard-constraint violation detected; temporal collision detected; cross-channel dedup/supersession works; `docs/IMPLICATION_BASELINE.md` has real numbers, including the hallucination rate.
- **Gate 5:** a reasoning agent cannot invoke T4/T5/T6 (proven by test); audit precedes every action; approval gate renders complete evidence bundles; expiry escalates; idempotency proven under forced replay; tool failure never fabricates success.
- **Gate 6:** ingesting a document makes the graph visibly grow in real time; derivation tags distinguishable at a glance; conflict edge unmissable; node click → source + region highlighted; path explainer legible; both themes correct, no raw hex; smooth at 500+ nodes.
- **Gate 7:** A28 cannot move money (inspect its registered tools directly); silent price hike detected from real price history; unused service flagged with usage evidence; handwritten register → correct salary or shows the image below confidence floor; SMS/ledger mismatch → dispute branch, no auto-resolution; double payment impossible under replay.
- **Gate 8:** chat export → confirmable cost matrix; solver deterministic (identical input → identical output); `docs/FAIRNESS_GUARANTEE.md` states exactly what's delivered, no overclaiming; verifier confirms the property holds; explanations reference the person's own valuations; a life-event trigger produces live re-allocation; capability constraints enforced pre-solve.
- **Gate 9:** stale obligation detected unprompted; blocker diagnosed to a specific type with rationale; each blocker type has a working unblock path; correction updates the friction profile; repeat slippage escalates with real options.
- **Gate 10:** "book a dentist" asks ≤2 questions; ranking explainable; approval fires before any call; disclosure on every call, non-disableable; out-of-bounds → declines + offers callback; slot-unavailable → adapts within bounds; unverified outcome never recorded (proven by test); failure ladder ends in useful human escalation.
- **Gate 11:** every branch claim traceable to graph data or a cited source with a retrieval timestamp; critic catches a planted over-optimistic assumption; calibration uses real variance, thin history acknowledged not fabricated; blast radius correctly identifies real breakage; trade-offs presented, no verdict on family choices.
- **Gate 12:** no two council agents share both tools and objective (proven by test); phase-1 isolation verified (no specialist observes another's output); Care's hard constraint eliminates options, never scores them down; delegates score from real behavioural profiles; adversary cites actual household history; resolution computed by deterministic code; R4 never auto-resolves; every position persists with evidence; the word "debate" appears nowhere.
- **Gate 13:** Hinglish utterance → correct per-span tags; code-mixed input drives the full pipeline; amounts read back digit-grouped and normalised; names read back with relationship; voice alone cannot approve R3 (proven by test); silence/ambiguity never counts as approval; unknown speaker restricted correctly; original-language text always retained; Marathi/Spanish work at demonstration depth.
- **Gate 14:** consolidation runs on schedule unattended; pattern mining produces ≥1 non-obvious correct pattern; protected node types provably never pruned; a real overnight run is captured in Cloud Logging with genuine timestamps; full trace available for any agent invocation.
- **Gate 15:** full 4-minute demo runs live end-to-end three times without intervention; all three mandatory requirements visibly proven on camera; `docs/DEPLOYMENT_PROOF.md` complete including the real overnight run; no Dockerfile; all eight invariants pass; `docs/DEBT.md` empty or fully justified; README enables clean-machine reproduction; backup recording exists; services scaled to zero after capture.
