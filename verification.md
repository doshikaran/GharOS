# GharOS — phase verification log

Append-only. One section per phase, in order, written by the CTO at gate time per the `gharos-gate-review` skill. Never edit a prior phase's section — if something later turns out wrong, note it under the *current* phase and reference back.

---

## Phase 0 — Foundation & Environment

**Gated:** 2026-08-22
**Roles active:** cto (lead), e1, e3, e4

### What was built

**CTO (0.A):**
- `contracts/` frozen: `graph_types.py` (16 node types, 29 edge types, `Provenance` mixin with a runtime-enforced guard), `repositories.py` (abstract protocols, zero Firestore leakage), `errors.py` (10 typed exceptions), `actions.py` (`RiskTier` R0-R4, `IdempotencyKey`, `EvidenceBundle`, `ActionResult[T]`, `Action`), `tools.py` (`PermissionTier` T0-T6/T5i, `GATED_TIERS`, tool protocols), `events.py` (Pub/Sub envelopes), `agents.py` (`AgentInput`/`AgentOutput`, `ModelTier`, `Citation`, `prompt_version` field).
- Six architecture diagrams in `docs/diagrams/` (system, layers, consequence engine, council, concierge, deployment), each with a short "reading this diagram" explanation beyond the bare mermaid source.
- Three ADRs: `001-firestore-edge-layout.md`, `002-result-vs-exception-policy.md`, `003-prompt-versioning.md`.
- Root config: `.gitignore`, `.env.example`, `Makefile`, `CLAUDE.md`, git repo initialized.
- `.claude/agents/{cto,e1,e2,e3,e4}.md` and `.claude/skills/{gharos-standards,gharos-gate-review,gharos-graph-model,gharos-agent-roster,gharos-tool-permissions}/SKILL.md` — written in full depth per operator instruction (these are process/meta artifacts, not phase deliverables per PHASES.md, but the operator asked for them explicitly this session).
- `docs/DEBT.md` created with one open entry (DEBT-001, see Gaps below).

**E1 (0.B):**
- `backend/` as a uv-managed Python 3.12 project (`pyproject.toml`, `requirements.txt`, `uv.lock`), deps include `google-adk>=2.7.1` (resolved fine on PyPI — no blocker there).
- `backend/app/main.py` (FastAPI app, `/health` endpoint), `backend/app/settings.py` (pydantic-settings, all 12 fields matching `.env.example`).
- `scripts/emulators.sh` — installs missing gcloud emulator components + Homebrew openjdk if needed, actually starts both emulators and verifies them listening on 8080/8085 before reporting success, backgrounds them with PID/log tracking.
- `backend/app/persistence/` — 9 in-memory stub repositories satisfying every `contracts/repositories.py` protocol, plus `conformance.py` proving structural conformance under mypy, plus a working provenance guard (raises `ProvenanceMissing`, proven unbypassable by a hypothesis fuzz test over all missing-field subsets).
- Placeholder packages for `backend/app/graph/`, `audit/`, `solvers/`, `migrations/`, `seeds/`, each documenting which future phase fills it in.
- `backend/tests/test_safety_invariants.py` — invariants #2 and #3 have real passing tests now; #1, #4, #5, #6, #7, #8 are `@pytest.mark.skip` placeholders naming their correct implementation phase.

**E3 (0.C):**
- `infra/setup_gcp.sh`, `budget_alert.sh`, `deploy_backend.sh`, `deploy_frontend.sh`, `teardown.sh`, `pubsub_topics.sh` (Phase 2 skeleton), `scheduler_jobs.sh` (Phase 2 skeleton), `firestore.rules` (deny-all client access, correct for a backend-only-write architecture), `_common.sh` (shared helpers) — all idempotent, all with hardcoded `--min-instances=0` with no override escape hatch, all with an explicit no-Dockerfile guard at deploy time.
- `backend/Procfile`.

**E4 (0.D):**
- `frontend/styles/tokens.css` — full token set both themes, WCAG contrast computed via the actual relative-luminance formula (not eyeballed), documented inline.
- `frontend/components/design-system/` — Button, Card, Badge, Dialog, Toggle, DerivationBadge (matches `contracts.graph_types.Derivation` values exactly; solid/dashed/dotted convention pre-established for the Phase 6 graph viz to reuse).
- Theme switcher (`next-themes`, `data-theme` attribute, no flash-of-wrong-theme), `/tokens` route rendering every token by category in both themes.
- Vitest + testing-library wired, 6 test files / 19 tests.

### Gate 0 checklist result

Re-verified independently by the CTO, not taken on report alone (see "Verified personally" below for exact commands run):

- [x] `contracts/` complete, importable, no Firestore or FastAPI imports inside
- [x] All six diagrams committed
- [x] `/tokens` renders correctly in both themes; contrast checked (WCAG relative-luminance computation, not eyeballed)
- [x] Emulators run locally (E1 started and verified both listening, then stopped cleanly; CTO independently checked script syntax)
- [ ] **Budget alert active; teardown.sh verified** — `teardown.sh` is written and idempotent (read in full, confirmed correct), but neither it nor `budget_alert.sh` has been run against a live project — **blocked on DEBT-001** (GCP billing account not active). `deploy_backend.sh`/`deploy_frontend.sh` reviewed in full, both enforce `--min-instances=0` with no override path.
- [x] No Dockerfile anywhere (`find . -iname "Dockerfile*"` excluding `node_modules` returns nothing)
- [x] Lint and types clean both sides (backend: `ruff check` clean, `mypy --strict app` clean on 18 files, `pytest` 42 passed/6 skipped, 86% coverage on `app/`; frontend: `eslint` clean, `tsc --noEmit` clean, `vitest` 19/19 passed)

**6 of 7 items pass outright. The 7th (budget alert) is blocked by an external account-activation issue, not a code or architecture defect — tracked as DEBT-001, not silently downgraded.**

### Verified personally (not just reported)

- Ran `python3 -c "import contracts.<every module>"` myself — all 7 import cleanly in isolation.
- Ran `grep -rniE "^\s*(import|from)\s+(firestore|fastapi|google\.cloud)" contracts/*.py` myself — zero hits.
- Ran `find . -iname "Dockerfile*"` myself (excluding node_modules) — zero hits.
- Re-ran `ruff check .`, `mypy --strict app`, `pytest -q` in `backend/` myself, independent of E1's own report — identical results (all clean, 42 passed/6 skipped).
- Re-ran `pnpm lint`, `pnpm exec tsc --noEmit`, `pnpm test` in `frontend/` myself, independent of E4's own report — identical results (clean, 19/19 passed).
- Ran `grep -rni "debate"` across `backend/`, `frontend/`, `infra/`, `scripts/`, `contracts/` myself — the only hits are in `test_safety_invariants.py`'s own docstring/table describing invariant #6 (i.e. the word appears only where it names the *forbidden* framing), which is correct, not a violation.
- Read `infra/setup_gcp.sh`, `infra/deploy_backend.sh`, `infra/teardown.sh`, `infra/firestore.rules` in full myself — confirmed the cost-control guards (`--min-instances=0` hardcoded, no Dockerfile check before deploy) are real code, not comments claiming a behavior.
- Independently confirmed the GCP billing blocker: checked `gcloud billing accounts list` and `gcloud billing projects describe` against both projects the operator created, before and after they switched projects — confirmed the block is the billing account's own activation state, not a per-project misconfiguration.

### Decisions / ADRs

- ADR-001: Firestore edge layout (node-per-collection, flat edges collection, composite indexes).
- ADR-002: Result-vs-exception policy (ActionResult for tool-layer outcomes, typed exceptions for reasoning/repository-layer conditions).
- ADR-003: Prompt versioning (versioned files per agent, manifest.json pins the active version, `AgentOutput.prompt_version` records provenance).

### Debt / deferred items

- **DEBT-001** (open): GCP billing account not active. Owner: operator. Repayment: before Phase 2 gates. Full detail in `docs/DEBT.md`.
- Noted but not formal debt (E1's report, logged here for continuity): root `.gitignore` was missing `.emulator-pids/`/`.emulator-logs/` — fixed directly by the CTO this session, no entry needed since it's already repaid.

### Open items for the operator

1. **DEBT-001** — please resolve the billing account activation (check the billing account's own console page for a pending-verification banner) so Phase 2 isn't blocked when we get there. Not urgent for Phase 1.
2. Two harmless leftover GCP projects: `gharos-20260822-50c6` (no billing, no cost) and `gharos-506312` (`DELETE_REQUESTED`, auto-purges). No action needed unless you want them gone sooner.
3. Environment note from E4: `frontend`'s pinned `jsdom@30` needs Node ≥22.22 for tests to run; the shell's default Node (nvm, 20.19.1) doesn't satisfy this. E4 added `frontend/.nvmrc` (`22`) as the documented fix — future sessions running frontend tests should `nvm use` first, or we standardize on Node 22+ project-wide. Not blocking (build/dev run fine on Node 20; only `vitest` needs 22+), just worth deciding on deliberately rather than re-discovering it by surprise later.

**Phase 0 gate: SIGNED, with DEBT-001 tracked and open.** Ready for Phase 1 pending operator go-ahead.

---

## Phase 1 — Graph substrate

**Gated:** 2026-08-22
**Roles active:** e1 (lead), cto
**Operator standard for this phase:** production-ready code, zero placeholders/TODOs, full architecture discipline — explicit instruction, verified against, not just asserted.

### What was built

**E1:** the entire Phase 0 in-memory stub layer under `backend/app/persistence/` was deleted and replaced with a real, Firestore-backed implementation (verified against the live emulator, not mocks):

- `backend/app/persistence/`: `firestore_client.py` (DI, no singleton), `collections.py` (16 node collections + flat `edges` collection per ADR-001), `codecs/` (explicit encode/decode for all 16 node types + Edge + Provenance), `provenance_guard.py` (the write-rejection guard), `firestore_store.py` (versioned writes, supersession, composite-index-backed queries), `idempotency_store.py`, `conformance.py`.
- `backend/app/graph/`: `reader.py` (all 14 spec §5.7 traversals — single-hop via composite-index queries, multi-hop via full-edge-set in-memory BFS/DFS per ADR-004), `writer.py`, `integrity_checker.py`, and Firestore-backed `person_repository.py` / `obligation_repository.py` / `decision_repository.py` / `pattern_repository.py`.
- `backend/app/audit/`: `audit_log.py` (`FirestoreAuditLog`), `write_before_execute.py` (`AuditGuardedAction` + `write_before_execute` — a Template Method pattern making "audit before execute" structurally unreachable to bypass, not just conventional).
- `backend/migrations/firestore_indexes.py`: real composite-index declarations + an Admin-API apply function (not yet run against live GCP — blocked by DEBT-001, not a code gap).
- `backend/seeds/demo_household.py` + `seed_loader.py`: a synthetic 36-node/46-edge household covering all 16 node types and 27 of the 29 edge types (the two ACTION_RECORD/APPROVAL_REQUEST-adjacent gaps are DEBT-002, not a seed-data omission).
- Full test suite rewritten against the real emulator: `test_serialization.py`, `test_provenance_guard.py` (+ unit variant), `test_versioning.py`, `test_traversals.py`, `test_integrity_checker.py`, `test_idempotency_store.py`, `test_audit_and_write_before_execute.py`, `test_seed_loader.py`, `test_firestore_client.py`, `test_conformance.py`, plus upgraded `test_safety_invariants.py` invariants #2/#3 (real implementations now; #1/#4/#5/#6/#7/#8 remain exactly as Phase 0's correctly-numbered skip placeholders).

**CTO:** ADR-004 (traversal strategy — single-hop via indexed queries, multi-hop via in-memory walk, graph-native store explicitly deferred with a measurable exit condition, not adopted speculatively). ADR-005 (removed the `argued_by` edge type — `AGENT` isn't a graph node type so it could never resolve; `CouncilPosition.held_by_agent` already carries the information). `docs/DEBT.md` DEBT-002 opened (ACTION_RECORD/APPROVAL_REQUEST graph connectivity, owned jointly, repayment at Phase 5). Corrected a real edge-type-count error in my own docs while fixing this (see "verified personally" below — the true pre-removal count was 30 members, not 29 as the spec table's row-count suggests, since `supports`/`opposes` is one table row for two distinct enum members).

### Gate 1 checklist result

- [x] Every node and edge type round-trips — `test_serialization.py`, all 16 node types + Edge, explicit encode→decode assertions
- [x] A provenance-less write is impossible, proven by hypothesis fuzz test — `test_provenance_guard.py`, `@given` over every non-empty subset of the 5 required fields, run against the real `FirestoreGraphWriter`
- [x] All 14 traversals implemented and tested — `test_traversals.py` against a 36-node/46-edge seeded graph with real multi-hop, conflicting-obligation, and resolved-Decision structure
- [x] `unexplained(scope)` empty on seeded graph — `test_seed_loader.py::test_unexplained_is_empty_gate_1`
- [x] Audit precedes side effects, proven by test — `test_audit_and_write_before_execute.py`; structurally enforced via `AuditGuardedAction`'s Template Method pattern, not just tested as a convention
- [x] Same idempotency key twice → one effect — `test_idempotency_store.py::TestCrashRecoveryStyleReplay`, including a simulated-restart scenario (fresh store instance, same underlying Firestore project)
- [x] Integrity checker clean on seed data — `test_integrity_checker.py::TestCleanOnSeededData`
- [x] ≥80% coverage on `graph/` and `persistence/`; 100% on the provenance guard — **97.6% / 96.9% / 100%**, see below

### Verified personally (not just reported)

Every number and claim below was independently reproduced by the CTO, starting the real emulator myself and re-running everything from a cold shell — not accepted from E1's report alone:

- `ruff check .` → clean. `ruff format --check .` → 51 files already formatted. `mypy --strict .` → clean, 51 source files.
- `pytest -q --cov=app --cov-report=term-missing` against the live emulator → **138 passed, 6 skipped, 0 failed.** Coverage: `app/graph/` 97.6% (329/337 stmts), `app/persistence/` 96.9% (376/388 stmts), `app/persistence/provenance_guard.py` **100%** (31/31 stmts) — every figure matches E1's report exactly, reproduced independently.
- `find . -iname "Dockerfile*"` (excluding node_modules) → empty.
- Grepped for "debate" across `backend/app/`, `backend/tests/`, `backend/seeds/`, `backend/migrations/` → the only hits are inside `test_safety_invariants.py`'s own docstring/table naming the *forbidden* framing for invariant #6 — correct, not a violation.
- Grepped for `TODO`/`FIXME`/`XXX`/`not.?implemented`/`placeholder` across all Phase 1 code → two hits, both read in full context and confirmed legitimate: (1) `reader.py`'s docstring honestly documenting that named-subgraph scope semantics are deferred (see ADR-004), not a missing required feature; (2) `write_before_execute.py`'s `NotImplementedError` is inside an ABC's `@abstractmethod` (`AuditGuardedAction._perform`) — exactly the one sanctioned exception to the zero-placeholder rule I gave E1, verified by reading the surrounding class and confirming it's a genuine Template Method pattern, not an unfinished implementation.
- Grepped for bare `except:` and `print(` across `backend/app/graph/`, `persistence/`, `audit/` → zero hits both.
- Confirmed Phase 0's stub persistence files were actually deleted, not left dangling alongside the new ones (`find backend/app/persistence -maxdepth 1 -name "*.py"` shows only the real Phase 1 files).
- Read `reader.py`'s and `write_before_execute.py`'s full source myself (not just the grep hit lines) to judge the two placeholder-scan hits above.
- Made the `EdgeType.ARGUED_BY` removal myself, then re-ran `mypy --strict` and the full `pytest` suite afterward to confirm the contract change didn't break anything downstream — clean, 138 passed / 6 skipped, unchanged.

### Decisions / ADRs

- ADR-004: traversal strategy (indexed single-hop, in-memory multi-hop) and explicit, evidence-based deferral of a graph-native store, with a measurable exit condition for revisiting.
- ADR-005: removal of the `argued_by` edge type (dead/unresolvable — `AGENT` is not a node type).

### Debt / deferred items

- **DEBT-001** (still open, unaffected by this phase): GCP billing account not active. Does not block Phase 1; will block Phase 2.
- **DEBT-002** (opened this phase): ACTION_RECORD/APPROVAL_REQUEST have no connecting graph edges yet. Owner: cto + e1 + e3. Repayment: Phase 5, when these nodes are first produced by real code.
- Noted, not formal debt: named-subgraph scope semantics (e.g. "the Ledger subgraph") are not yet implemented — `scope` is currently `"all"` vs. a single `NodeId`. This becomes load-bearing at Phase 12 (Council needs mutually-distinct T0 subgraph scopes, enforced not conventional) — flagged in ADR-004 as forward-looking context for whoever picks up Phase 12, not a Phase 1 shortfall.

### Open items for the operator

1. DEBT-001 (billing) still open — no change this phase, doesn't block Phase 2 planning but will block Phase 2's actual gate.
2. Everything else: clean. No new operator action needed to proceed.

**Phase 1 gate: SIGNED.** Ready for Phase 2 pending operator go-ahead — but note Phase 2 (Mandatory Stack Proof) hard-requires live GCP, so DEBT-001 needs resolving before Phase 2 can gate, even though Phase 1 didn't need it.
