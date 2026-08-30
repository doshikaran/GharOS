# GharOS

**An autonomous household operating system.** GharOS ingests the messy multi-channel stream a family actually receives — school emails, WhatsApp threads, UPI SMS, scanned notices, bills, photographed forms — reasons about what each item *implies*, records everything in a walkable, provenance-tagged knowledge graph, assigns the resulting obligations fairly, drives them to completion, watches the financial surface continuously, executes in the outside world (calls, bookings, claims) behind an approval gate, and convenes a council of specialised sub-agents when a decision is genuinely hard.

Built for the Google **"All Things Agentic"** hackathon (Devpost) — **Taskmaster** track. One household, single-tenant. Every capability anchors to a reasoning step a script cannot perform.

- **What it is (the spec):** [`GharOS_Build_Spec_v2.md`](./GharOS_Build_Spec_v2.md) — every entity, agent, tool, permission tier, failure mode. Read-only reference.
- **How it was built (gated plan):** [`PHASES.md`](./PHASES.md) — 15 phases, one gate each.
- **What passed each gate:** [`verification.md`](./verification.md) — one signed section per phase.
- **Architecture diagrams:** [`docs/diagrams/`](./docs/diagrams/) — `01-system.md` is the top-level view.
- **Deployment proof:** [`docs/DEPLOYMENT_PROOF.md`](./docs/DEPLOYMENT_PROOF.md) — real command output against the real Google Cloud project.
- **Honest scope / limitations for the write-up:** [`docs/SUBMISSION_NOTES.md`](./docs/SUBMISSION_NOTES.md).
- **Tracked debt:** [`docs/DEBT.md`](./docs/DEBT.md) — every item struck or CTO-justified.
- **Fairness guarantee (exact, code-matching):** [`docs/FAIRNESS_GUARANTEE.md`](./docs/FAIRNESS_GUARANTEE.md).
- **Implication-agent honest baseline:** [`docs/IMPLICATION_BASELINE.md`](./docs/IMPLICATION_BASELINE.md).
- **Decision records:** [`docs/adr/`](./docs/adr/) — 23 ADRs.

All demo data is synthetic. No real family data, financial credentials, or medical records anywhere in this repository.

---

## Mandatory-requirement mapping

| Requirement | Satisfied by | Proven in |
|---|---|---|
| **1. Gemini 3.5+ via Vertex AI** | Every reasoning agent calls Vertex AI through `backend/app/reasoning/gemini_client.py`; Flash / Pro-tier routing and the Pro-tier allowlist are enforced in `backend/app/reasoning/model_router.py` | `docs/DEPLOYMENT_PROOF.md` Requirement 1; tests `backend/tests/test_model_router.py`, `test_gemini_client.py`, `test_live_gemini_intake.py` |
| **2. A Google Agent Framework — Google ADK** | `backend/app/agents/` — A0 Household Coordinator + the 69-agent roster; sequential/parallel/loop orchestration, `FunctionTool` isolation, approval-gate callbacks. Reference wiring: `backend/app/agents/orchestration/stack_proof_agent.py` | `docs/DEPLOYMENT_PROOF.md` Requirement 2 |
| **3. A Google Cloud infrastructure service** | Cloud Run (both services, source deploys, `min-instances=0`), Firestore Native (the graph), Cloud Pub/Sub (events), Cloud Scheduler (heartbeat + nightly consolidation + follow-up sweep). Scripts: `infra/` | `docs/DEPLOYMENT_PROOF.md` Requirements 3 & 4 |
| **Deployment proof (not live at judging)** | Console screenshots, source-build revision detail, a real unattended overnight Cloud Logging run, `infra/` scripts | `docs/DEPLOYMENT_PROOF.md` |

**There is no `Dockerfile` anywhere in this repository.** Cloud Run deploys from source via buildpacks (`gcloud run deploy --source .`). Its absence is a gate item at Phase 2 and Phase 15 — verify with `find . -iname "Dockerfile*"` (empty).

---

## Prerequisites (clean machine)

| Tool | Version | Notes |
|---|---|---|
| Python | **3.13+** | `requires-python = ">=3.13"` (migrated from 3.12 in Phase 2 — Google's buildpack builder dropped 3.12, ADR-006) |
| [`uv`](https://docs.astral.sh/uv/) | latest | Python dependency + venv manager. `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Node.js | **22 LTS** | |
| [`pnpm`](https://pnpm.io/) | **9.15+** | pinned via `packageManager` in `frontend/package.json`. `corepack enable` picks it up automatically |
| Google Cloud CLI (`gcloud`) | latest | Needed for the local **emulators** (`cloud-firestore-emulator`, `pubsub-emulator`, `beta` components — `scripts/emulators.sh` installs them if missing) and for deploy. `brew install --cask google-cloud-sdk` or see cloud.google.com/sdk |
| A Java runtime (JRE) | 11+ | The Firestore/Pub/Sub emulators are JVM-based. `scripts/emulators.sh` falls back to Homebrew's keg-only `openjdk` without touching your system default |
| `make` | any | task entry points; see `Makefile` |

A real Google Cloud project is **only** needed to deploy or to run the `live_gcp`-marked tests. Everything else — the full test suite, the demo seed, both dev servers — runs against local emulators with no cloud spend.

---

## Repository layout

```
GharOS/
├── contracts/            # CTO-owned frozen interfaces — graph_types, repositories,
│                         #   tools, agents, actions, errors, events, ingestion
├── backend/
│   ├── app/
│   │   ├── main.py  settings.py
│   │   ├── api/              # FastAPI routers (graph, ingest, oauth, voice, pubsub_receiver, debug)
│   │   ├── graph/ persistence/ audit/ solvers/   # E1 — the graph substrate, deterministic solvers
│   │   ├── agents/           # E2 — the 69-agent roster (A0–A69), by subsystem
│   │   ├── reasoning/ prompts/   # E2 — model routing, confidence, versioned prompts
│   │   ├── tools/ adapters/ events/ voice/ pipelines/  # E3 — tools by permission tier,
│   │   │                     #   ingestion adapters + connectors, Pub/Sub, voice, the ingestion orchestrator
│   │   └── arbitration/      # the Confidence Arbiter + Approval Gate — the only path to action
│   ├── migrations/ seeds/    # E1 — schema migrations, the demo-household seed
│   ├── tests/                # pytest — unit, contract, integration (emulator), golden, evaluation
│   │   └── test_safety_invariants.py   # the eight invariants, one real test each, never skipped
│   ├── pyproject.toml  requirements.txt  Procfile
├── frontend/                 # E4 — Next.js 15 + TypeScript, Tailwind v4, D3 graph viz
│   ├── app/                  # (landing) standalone landing at /, (shell) the app routes
│   ├── components/  lib/  styles/tokens.css
├── infra/                    # E3 — setup_gcp, pubsub_topics, scheduler_jobs,
│                             #   deploy_backend, deploy_frontend, teardown, firestore.rules
├── scripts/                  # emulators.sh, seed_demo.sh
├── docs/                     # adr/ diagrams/ + DEBT, DEPLOYMENT_PROOF, FAIRNESS_GUARANTEE,
│                             #   IMPLICATION_BASELINE, SUBMISSION_NOTES, PROGRESS
├── Makefile  .env.example  CLAUDE.md
└── GharOS_Build_Spec_v2.md  PHASES.md  verification.md
```

---

## Local setup, step by step

```bash
# 1. Clone, then from the repo root:
cp .env.example backend/.env
#    The defaults are correct for local emulator dev (FIRESTORE_EMULATOR_HOST=localhost:8080,
#    PUBSUB_EMULATOR_HOST=localhost:8085). Leave GCP_PROJECT_ID and the OAuth vars blank
#    unless you are connecting a real Gmail/Outlook account (see "Ingestion connectors" below).

# 2. Backend dependencies (creates backend/.venv from the lockfile):
cd backend && uv sync && cd ..

# 3. Frontend dependencies:
cd frontend && pnpm install && cd ..
```

### Run the Firestore + Pub/Sub emulators

In their own terminal, from the repo root:

```bash
make emulators        # -> scripts/emulators.sh
```

This starts both emulators as background processes, writes their PIDs to `.emulator-pids/`, logs to `.emulator-logs/`, and prints the exact `FIRESTORE_EMULATOR_HOST` / `PUBSUB_EMULATOR_HOST` values (they match `.env.example`). Stop them with `kill $(cat .emulator-pids/*.pid)`.

> If a suite mass-fails with `ServiceUnavailable`, a stale emulator process from an earlier session is usually the cause — kill everything on ports 8080/8085 and re-run `make emulators`.

### Run the backend

```bash
make dev-backend      # cd backend && uv run uvicorn app.main:app --reload --port 8000
```

API on `http://localhost:8000`. OpenAPI at `/docs`. Health/debug: `/debug/gemini-ping`, `/debug/adk-demo` (these need a real GCP project + `gcloud auth application-default login`).

### Run the frontend

```bash
make dev-frontend     # cd frontend && pnpm dev
```

App on `http://localhost:3000`. `NEXT_PUBLIC_API_BASE_URL` defaults to `http://localhost:8000` when unset. Routes: `/` (landing), `/graph`, `/approvals`, `/concierge`, `/connections`, `/council`, `/fair-allocator`, `/intention-action`, `/ledger`, `/simulator`, `/voice`, `/story`, `/status`, `/tokens`.

### Load the demo household

With the emulators running:

```bash
make seed-demo        # -> scripts/seed_demo.sh
```

The seed writes the demo household — roster, hard constraints, ugly documents, three months of financial signals, OUTCOME history for calibration, and the engineered verification receipt — through the **real provenance-guarded `FirestoreGraphWriter`** (`backend/seeds/seed_loader.py` + `demo_household.py`), never by writing to Firestore directly, so seeded data is held to the same standard as ingested data. `scripts/seed_demo.sh` is the operator-facing CLI over that loader (finalised in Phase 15 by E1 — the underlying `seed_loader` has existed since Phase 1). Re-running is safe: `write_node` versions rather than errors; run it once against a fresh emulator database.

---

## Run the test suites

```bash
# Backend — needs the emulators running (integration tests hit the real Firestore emulator, not mocks):
make emulators                 # in another terminal, if not already up
make test-backend              # cd backend && uv run pytest --cov=app --cov-report=term-missing
#   ~1750 tests. ~12 are skipped by design — they are `live_gcp`-marked and hit real Vertex AI /
#   Secret Manager over the network; enable with GHAROS_RUN_LIVE_GCP_TESTS=1 and a real GCP_PROJECT_ID.

make lint-backend              # cd backend && uv run ruff check . && uv run mypy --strict app

# Frontend:
make test-frontend             # cd frontend && pnpm test   (vitest, ~790 tests)
make lint-frontend             # cd frontend && pnpm lint && pnpm exec tsc --noEmit
```

The eight safety invariants live in `backend/tests/test_safety_invariants.py` — one real test each, never `skip`, never `xfail`. See `docs/SUBMISSION_NOTES.md` § "Safety invariants" for where each is enforced.

---

## Ingestion connectors (optional — real Gmail / Outlook)

Phase 14.5 added real OAuth "scan my last 24 hours of mail" for Gmail and Outlook, a drag-drop / Google Drive picker path, all behind one synchronous `POST /ingest`. Running these against real accounts needs credentials only the project owner can create (a Google Cloud OAuth 2.0 Web client in **Testing** publishing status; an Azure app registration) — the full list is in `verification.md` § Phase 14.5 "Open items for the operator" and `docs/adr/022-oauth-in-a-backend-only-architecture.md`. Without them, the connector code paths are exercised against fakes in the test suite. Google restricted scopes run in **OAuth test mode** (7-day refresh token, <100 users) — a real, stated limitation; see `docs/SUBMISSION_NOTES.md`. There is **no** local-filesystem / Apple Photos / iMessage / WhatsApp read from the deployed web app; that needs a native companion and is roadmap only.

---

## Deploy to Google Cloud (source deploys, no Docker)

First-time project setup (idempotent):

```bash
./infra/setup_gcp.sh          # project APIs, Firestore Native (asia-south1)
./infra/budget_alert.sh       # currency-aware budget alert
./infra/pubsub_topics.sh      # topics + OIDC-verified push subscriptions
./infra/scheduler_jobs.sh     # heartbeat, nightly consolidation (03:00 IST), follow-up sweep
```

Deploy / redeploy:

```bash
make deploy-backend           # ./infra/deploy_backend.sh  -> gcloud run deploy gharos-api --source ./backend
make deploy-frontend          # ./infra/deploy_frontend.sh -> gcloud run deploy gharos-web --source ./frontend
```

Both services deploy via **buildpacks** (no Dockerfile), with `--min-instances=0 --max-instances=2` — never overridden. `deploy_backend.sh` looks up `gharos-web`'s real URL for the CORS allowlist; `deploy_frontend.sh` passes `NEXT_PUBLIC_API_BASE_URL` as a **build-time** env var (Next.js inlines it into the client bundle).

After capturing any proof:

```bash
make teardown                 # ./infra/teardown.sh — scales both Cloud Run services to zero
```

Revision history and Cloud Logging stay intact; compute cost goes to zero until the next deploy.

---

## Tech stack (fixed — PHASES.md §3)

Python 3.13 + FastAPI · Google ADK · Gemini 3.5+ via Vertex AI · Firestore (Native) · Cloud Pub/Sub · Cloud Run (source deploys, `min-instances=0`) · Cloud Scheduler · Next.js 15 + TypeScript · Tailwind CSS v4 · D3 · `uv` / `pnpm` · `ruff` + `mypy --strict` / `eslint` + `tsc` · `pytest` / `vitest`.
