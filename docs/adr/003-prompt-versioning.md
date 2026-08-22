# ADR-003: Prompt versioning

**Status:** accepted
**Phase:** 0
**Date:** 2026-08-22

## Context

`backend/app/prompts/` (E2-owned) holds prompts for every LLM-backed agent
in the 69-agent roster (spec §15). Spec §22 requires every agent
invocation be traceable ("inputs consulted, outputs produced, model tier,
confidence, latency"), and PHASES.md Phase 15 requires "prompt versions
pinned" for demo determinism. Without an explicit versioning scheme,
prompt iteration during development would silently change agent behaviour
between two runs with no record of which prompt produced which graph
state — unacceptable for a system whose entire pitch is auditability.

## Decision

- One directory per agent under `backend/app/prompts/`, named by agent ID
  in lowercase with its short name, e.g. `prompts/a12_implication/`.
- Each prompt version is a separate file: `v1.md`, `v2.md`, ... Prompts are
  never edited in place once referenced by any recorded `AgentOutput` —
  a change is a new version file, not a diff to an existing one (mirrors
  the graph's own "writes create versions" discipline, PHASES.md §2.2).
- `prompts/manifest.json` maps `agent_id → active_version` for every
  LLM-backed agent. The model router / agent orchestration layer reads
  this manifest at startup, not a hardcoded string, so pinning a version
  for demo day (Phase 15) is a one-file change.
- `contracts.agents.AgentOutput.prompt_version` records which version
  produced every output, as a plain string matching the version file name
  (e.g. `"v2"`). Agents with `ModelTier.DETERMINISTIC` (no LLM call) record
  `"deterministic"`.
- Prompt changes are ordinary code changes — reviewed, committed, and
  (per `gharos-standards`) any prompt-driven behaviour change significant
  enough to affect a gate's outcome gets a note in the relevant phase's
  gate review, not just a manifest bump.

## Alternatives considered

- **Prompts inline in agent code as string literals.** Rejected: makes
  prompt iteration indistinguishable from logic changes in diffs, and
  gives no natural place to record which version an output used.
  Undermines PHASES.md Phase 15's "prompt versions pinned" requirement.
- **A prompt registry service / database instead of versioned files.**
  Rejected as unnecessary complexity for a single-household, single-tenant
  system (spec §3.1 track discipline) — flat files under version control
  are sufficient and keep prompt history in git, not a second system of
  record.

## Consequences

- Any `AgentOutput` can be traced back to the exact prompt text that
  produced it, which is required for the "personally inspect" style gate
  reviews (`gharos-gate-review` skill) and for honestly reporting the
  Implication Agent's hallucination baseline (`docs/IMPLICATION_BASELINE.md`,
  Phase 4) against a fixed, known prompt version.
- E2 must remember to bump `manifest.json` deliberately, not accidentally
  leave a demo running against an unpinned "latest" pointer — there is no
  "latest" pointer by design; the manifest always names an exact version.
