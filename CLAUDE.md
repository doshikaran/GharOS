# GharOS

Autonomous household operating system — built for the Google "All Things Agentic" hackathon (Devpost), Taskmaster track. Submission window Aug 3-31, 2026.

## Read first, every session

1. `GharOS_Build_Spec_v2.md` — the WHAT. Defines every entity, agent, tool, permission tier, and failure mode. Read-only reference; never edited by any role.
2. `PHASES.md` — the HOW and WHEN. Phased build plan, gated, executed by five roles.
3. `docs/PROGRESS.md` — current phase, gate status, and open decisions, kept up to date at the end of every work session.

## The team

Five roles, each a Claude Code subagent defined in `.claude/agents/`:

| Role | Owns |
|---|---|
| `cto` | `contracts/`, `docs/adr/`, `README.md`, `PHASES.md`, root config — architecture, contracts, gate reviews, ADRs |
| `e1` | `backend/app/graph/`, `persistence/`, `audit/`, `solvers/`, `migrations/`, `seeds/` — the knowledge graph substrate |
| `e2` | `backend/app/agents/`, `reasoning/`, `prompts/` — ADK agents, Gemini integration, model routing |
| `e3` | `backend/app/tools/`, `adapters/`, `events/`, `voice/`, `infra/`, `scripts/` — tools, ingestion, deployment |
| `e4` | `frontend/` — Next.js app, design system, graph visualisation, approval UI |

File ownership is hard, not advisory (PHASES.md §1.1) — a role needing a change outside its directories raises it to `cto` rather than editing it directly. This is what makes parallel work across roles safe.

**Execution pattern:** the CTO freezes a phase's contracts first; only then do E1-E4 work, typically in parallel via the `Agent` tool (`subagent_type: e1|e2|e3|e4`).

## Shared skills (`.claude/skills/`)

Every role loads the relevant ones before implementation work:

- `gharos-standards` — engineering rules, architecture patterns, testing requirements, cost rules, the eight safety invariants, definition of done
- `gharos-gate-review` — how to run a phase's Green-Light Gate, verify claims directly rather than trusting summaries, write an ADR, and write the phase summary into `verification.md`
- `gharos-graph-model` — the complete Household Knowledge Graph reference: all node/edge types, the Document-Type Registry, verification-document model, provenance rules, the 14 query operations
- `gharos-agent-roster` — the complete 69-agent roster (A0-A69) with model tier, forbidden list, and I/O contract per agent
- `gharos-tool-permissions` — the complete tool inventory, permission tiers (T0-T6/T5i), risk tiers (R0-R4), isolation invariants, and legal/security constraints

## Standing rules (PHASES.md Appendix D)

1. Read the spec before coding. `PHASES.md` is the plan; `GharOS_Build_Spec_v2.md` is the truth.
2. Never start a phase whose dependencies have not passed their gate.
3. Never edit outside your owned directories.
4. Contracts change only via the CTO.
5. **No Docker. Ever.** Cloud Run source deploys via buildpacks only.
6. Never set `min-instances` above 0.
7. Never say "debate" — the Council is specialization and interest representation, not debate (spec §12.2).
8. Never fabricate a success — a failed tool call is reported as a failure.
9. On a safety path, when torn between fast and correct — ship correct.
10. If a gate item cannot be met, escalate to the CTO. Never silently downgrade it.

## Operator's phase-gating protocol (binding, overrides any efficiency instinct)

**Run exactly one phase at a time.** Never dispatch or plan work for phase N+1 while phase N is open. At the end of a phase: run the Green-Light Gate, write the phase's summary into `verification.md` (repo root, append-only, one section per phase — see `gharos-gate-review` skill for the exact template), and present that summary to the operator. Then stop and wait for the operator's explicit instruction to proceed — do not continue into the next phase unprompted.

## Tech stack (fixed — see PHASES.md §3)

Python 3.12 + FastAPI · Google ADK · Gemini 3.5+ via Vertex AI · Firestore (Native) · Cloud Pub/Sub · Cloud Run (source deploys, `min-instances=0`) · Cloud Scheduler · Next.js 15 + TypeScript · Tailwind CSS v4 · D3 (or Cytoscape.js) · `uv` / `pnpm` · `ruff` + `mypy` / `eslint` + `prettier` · `pytest` / `vitest`.
