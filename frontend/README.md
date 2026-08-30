# GharOS frontend (`gharos-web`)

Next.js 15 (App Router) + TypeScript + Tailwind v4. The design system, the
force-directed household knowledge graph, the approval / escalation surfaces, and
one page per subsystem. Deployed to Cloud Run as `gharos-web`; talks to
`gharos-api` over HTTP + SSE.

## Clean-machine setup

Requires **Node 22** (`.nvmrc`) and **pnpm 9** (`packageManager` in `package.json`).

```bash
nvm use 22           # or: nvm install 22 && nvm use 22
corepack enable       # picks up the pinned pnpm from package.json
cd frontend
pnpm install --frozen-lockfile
cp .env.example .env.local   # then edit — see "Environment variables" below
```

## Run

```bash
pnpm dev     # dev server on http://localhost:3000 (expects gharos-api on :8000)
pnpm build   # production build; also the CI gate — must list all app routes
pnpm start   # serve the production build locally
```

From the repo root, `make dev-frontend` / `make dev-backend` / `make seed-demo`
bring up the whole local stack (Firestore + Pub/Sub emulators, `gharos-api`, the
demo household seed). The frontend defaults to `http://localhost:8000` for the API,
so with the emulator stack up `pnpm dev` needs no extra configuration.

## Checks (Definition of Done — all must be clean)

```bash
pnpm lint                 # eslint (flat config, eslint-config-next)
pnpm exec tsc --noEmit    # strict TypeScript, no errors
pnpm test                 # vitest, jsdom — full suite
pnpm build                # next build — all 15 routes in the output
```

`make lint-frontend` runs the first two together.

### Test suite notes

The suite is ~120 jsdom files. `vitest.config.mts` caps the worker pool
(`poolOptions.forks.maxForks`) and widens `testTimeout` because the default
one-worker-per-CPU fan-out exhausts memory on an 8 GB machine and turns
CPU-starvation stalls into spurious timeouts. If you have plenty of RAM you can
raise `maxForks` for a faster run.

## Environment variables

Copy `.env.example` to `.env.local` (gitignored). All are `NEXT_PUBLIC_*`, so
Next.js **inlines them at `next build` time** — a deployed build cannot pick them
up at container runtime; they must be passed as build/deploy-time vars to the
`gharos-web` deploy. See `lib/api-base-url.ts` and `lib/drive-picker.ts`.

| Variable | Required | Purpose |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | no (defaults to `http://localhost:8000`) | Base URL of the `gharos-api` backend. Read by `/status`, `/graph`, `/ledger`, `/fair-allocator`, `/concierge`, `/voice`, `/council` (history browser), `/connections`. |
| `NEXT_PUBLIC_GOOGLE_PICKER_API_KEY` | no | Browser API key for the Google Drive file picker on `/connections`. When unset, the picker button shows a "needs browser configuration" note and drag-and-drop / direct upload still work. |
| `NEXT_PUBLIC_GOOGLE_APP_ID` | no | Google Cloud project number, also required by the Drive picker. Same graceful degradation as above when unset. |

## Routes

`/` landing · `/story` narrative · `/graph` knowledge graph · `/approvals` approval
queue + escalation surface · `/status` stack status · `/ledger` · `/fair-allocator`
· `/intention-action` · `/concierge` · `/simulator` · `/council` · `/voice` ·
`/connections` ingestion · `/tokens` design-system reference (both themes).

## Demo

`DEMO_SCRIPT.md` (this directory) is the filmed-rehearsal runbook: pre-flight
checklist, the eight §24 beats with click-paths and fallbacks, and the
backup-recording storyboard.
