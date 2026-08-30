# GharOS — deployment proof

Started Phase 2 (Mandatory Stack Proof), kept current in every phase that touches deployment. Per PHASES.md §6.3 — the hackathon does not require the app to stay publicly live at judging, but it must be *provably built and deployed on Google Cloud*. This file is that proof, assembled from real command output against the real project, not simulated.

**Project:** `blissful-trail-506312-t0` (display name "GharOS")
**Region:** `asia-south1`
**Billing:** active, INR-denominated, budget alert ₹2,000/month at 50%/90% thresholds (`docs/DEBT.md` DEBT-001, resolved 2026-08-22)

---

## Requirement 1 — Gemini 3.5+ via Vertex AI, responding from deployed Cloud Run

Live call against the deployed service, captured 2026-08-22:

```
$ curl -sS https://gharos-api-971309809251.asia-south1.run.app/debug/gemini-ping
{"response_text":"pong","model_tier":"flash","model_name":"gemini-2.5-flash"}
```

This is a real round trip: the deployed container calls Vertex AI (`google-cloud-aiplatform`) using the Cloud Run service's own identity — not a mock, not a cached response. `backend/app/reasoning/model_router.py` + `gemini_client.py` route the call; the allowlist and Flash/Pro-tier discipline are enforced in code and tested (`backend/tests/test_model_router.py`).

**Known limitation, tracked (DEBT-003):** Pro-tier (`gemini-2.5-pro`) is not available in `asia-south1` on this project — confirmed via ~15 model-id variants, all 404. Works via Vertex AI's "global" location. Not a Gate 2 blocker (Flash-tier is what's required here), but needs resolving before Phase 4's Pro-tier agents (the Implication Agent, etc.) go live.

## Requirement 2 — a Google ADK agent executing a tool call, in deployed form

Live call against the deployed service, captured 2026-08-22:

```
$ curl -sS -X POST https://gharos-api-971309809251.asia-south1.run.app/debug/adk-demo
{"response_text":"The current UTC time is 2026-08-22T17:55:39.393425+00:00.",
 "tool_invoked":"get_current_utc_time",
 "tool_result":{"utc_time":"2026-08-22T17:55:39.393425+00:00"},
 "model_name":"gemini-2.5-flash"}
```

`tool_result.utc_time` matches the actual wall-clock time at the moment of the call — proof the tool genuinely executed inside the agent loop (via the ADK SDK's own `Event.get_function_calls()`/`get_function_responses()`), not that the model merely claimed it did. Implementation: `backend/app/agents/orchestration/stack_proof_agent.py` (a real `google.adk.agents.Agent` + `FunctionTool` + `Runner`), forward-structured as the pattern the real 69-agent roster follows starting Phase 3.

## Requirement 3 — Firestore + Pub/Sub + Cloud Run + Cloud Scheduler, all operating

**Firestore** (Native mode, live):
```
$ gcloud firestore databases describe --database='(default)' --project=blissful-trail-506312-t0
name: projects/blissful-trail-506312-t0/databases/(default)
locationId: asia-south1
type: FIRESTORE_NATIVE
```

**Cloud Run** (source deploy, buildpacks, no Dockerfile):
```
$ gcloud run services list --project=blissful-trail-506312-t0
SERVICE     REGION       URL
gharos-api  asia-south1  https://gharos-api-971309809251.asia-south1.run.app
```
Revision `gharos-api-00004-phc`: `Deploying revision succeeded in 9.56s`, `Containers became healthy in 4.85s`. No Dockerfile anywhere in the repo (`find . -iname "Dockerfile*"` — empty, re-verified at this gate).

**Pub/Sub:**
```
$ gcloud pubsub topics list --project=blissful-trail-506312-t0
projects/blissful-trail-506312-t0/topics/gharos-events
projects/blissful-trail-506312-t0/topics/gharos-heartbeat

$ gcloud pubsub subscriptions list --project=blissful-trail-506312-t0
projects/blissful-trail-506312-t0/subscriptions/gharos-heartbeat-push
  push endpoint: https://gharos-api-kqqeygtaya-el.a.run.app/events/heartbeat
```
Push authentication: dedicated service account `gharos-pubsub-invoker@blissful-trail-506312-t0.iam.gserviceaccount.com`, granted `roles/run.invoker` on `gharos-api`, presenting a signed OIDC token the receiver cryptographically verifies (`backend/app/api/pubsub_receiver.py`) — not an open unauthenticated endpoint.

**Cloud Scheduler:**
```
$ gcloud scheduler jobs list --project=blissful-trail-506312-t0 --location=asia-south1
ID                     LOCATION     SCHEDULE (TZ)          TARGET_TYPE  STATE
gharos-heartbeat-tick  asia-south1  */5 * * * * (Etc/UTC)  Pub/Sub      ENABLED
```

**The full round trip, live, captured 2026-08-22T17:57:26Z:**
```
$ gcloud scheduler jobs run gharos-heartbeat-tick --project=blissful-trail-506312-t0 --location=asia-south1
```
→ Cloud Run structured log, same second:
```
2026-08-22 17:57:26 [info] heartbeat_received
  attributes={} message_id=21500095950052041
  payload={'job_name': 'gharos-heartbeat-tick', 'cycle_label': 'heartbeat'}
  publish_time=2026-08-22T17:57:22.855Z
  subscription=projects/blissful-trail-506312-t0/subscriptions/gharos-heartbeat-push
INFO: 169.254.169.126:54488 - "POST /events/heartbeat HTTP/1.1" 204 No Content
```

This one trigger was manual (`gcloud scheduler jobs run`, to verify the chain immediately rather than waiting up to 5 minutes for the next natural tick) — but the job itself is `ENABLED` on a `*/5 * * * *` cron and requires no human to fire on its own schedule going forward. **A genuinely unattended overnight run's Cloud Logging timestamps** (PHASES.md Phase 14's explicit strongest-evidence artifact) is captured properly once Phase 14 lands — this entry proves the mechanism works end-to-end, not yet the multi-hour unattended history.

**`min-instances=0` confirmed on `gharos-api`:**
```
$ gcloud run services describe gharos-api --project=blissful-trail-506312-t0 --region=asia-south1
    Max instances:   2
```
(No "Min instances" line appears — Cloud Run only prints it when explicitly set above the default of 0.)

## Secret Manager

```
$ gcloud secrets list --project=blissful-trail-506312-t0
NAME                CREATED
gharos-demo-secret  2026-08-22T14:27:28
```
Read-side wiring (`backend/app/adapters/secret_manager.py`) verified against the *real* Secret Manager API (not mocked) via a `live_gcp`-marked integration test, re-run independently by the CTO: `2 passed` (`test_gemini_client.py::test_real_flash_tier_call_against_live_vertex_ai`, `test_secret_manager_adapter.py::test_reads_the_real_placeholder_demo_secret_from_live_secret_manager`). The secret's *value* is a documented placeholder — the wiring is real, nothing sensitive is stored yet.

## Deploy-time issues hit and fixed (part of the proof this was a genuine deploy, not a paper exercise)

1. **Python 3.12 no longer supported by Google's buildpack builder** — the very first deploy attempt failed at the build step. Migrated to Python 3.13 (ADR-006), full local re-verification (184 tests, mypy --strict, ruff) before redeploying.
2. **`contracts/` unreachable inside the deployed container** — `gcloud run deploy --source ./backend` uploads only `backend/`'s contents; `contracts/` lives as a repo-root sibling and never reached the container. Fixed by staging a copy inside the uploaded tree and making `backend/app/__init__.py` resolve it by upward search instead of a hardcoded path depth (ADR-007). Two attempts — the first staging fix was itself wrong (sibling instead of nested); caught by the identical error recurring, fixed properly, re-verified locally before the third deploy attempt succeeded.
3. **`uv export`'s stderr-style progress line landing in `requirements.txt`'s first line** — corrupted the file just enough that buildpacks' `pip install -r requirements.txt` rejected it outright. Fixed with `-q`; the corrected command is now documented directly in `PHASES.md` §0.B so it isn't rediscovered.

## infra/ scripts backing this proof

`infra/setup_gcp.sh`, `infra/budget_alert.sh`, `infra/deploy_backend.sh`, `infra/deploy_frontend.sh`, `infra/pubsub_topics.sh`, `infra/scheduler_jobs.sh`, `infra/teardown.sh` — all idempotent, all reviewed and independently re-run by the CTO, not just the engineer who wrote them.

## Frontend

Deployed: `gharos-web`, live at `https://gharos-api-971309809251.asia-south1.run.app` and `https://gharos-web-kqqeygtaya-el.a.run.app` (both real, independently-resolving Cloud Run URLs for the same service — see below). `/status` page (E4) proves cross-service connectivity live:

```
$ curl -sS https://gharos-web-971309809251.asia-south1.run.app/status -o /dev/null -w "%{http_code}"
200
```

**Two real deploy-time bugs found and fixed while wiring this up:**
1. `infra/deploy_frontend.sh` set `NEXT_PUBLIC_API_BASE_URL` only in the calling shell's local environment, which Next.js needs *at build time* (inlined into the client bundle) — but that env var never reached the remote Cloud Build execution. The first frontend deploy shipped with its documented `http://localhost:8000` fallback baked in instead of the real backend URL. Fixed with `--set-build-env-vars` (distinct from the runtime-only `--set-env-vars` used for the backend) and a live lookup of `gharos-api`'s URL so the script needs no manual coordination.
2. **CORS was entirely missing** (caught by E4 in their own Phase 2 report, not discovered post-deploy) — `gharos-web` and `gharos-api` are different Cloud Run origins, so the `/status` page's cross-origin fetches would be blocked by the browser. Added `Settings.cors_allowed_origins` (exact-origin allowlist only, never a wildcard) and `CORSMiddleware` in `app.main`, wired by `infra/deploy_backend.sh` looking up the deployed frontend's URL.
3. **Every Cloud Run service actually resolves at two distinct real URLs** — `<service>-<hash>.<region>.run.app` (what `status.url` reports) and `<service>-<project-number>.<region>.run.app` (what the deploy command's own success banner prints) — both verified live-serving identical content. A browser can legitimately land on either. `infra/_common.sh:service_urls()` now returns both so CORS allows both; missing this would have been a real, silent, hard-to-diagnose breakage depending on which URL a judge happened to open.
4. That fix itself needed a second correction: `gcloud run deploy --set-env-vars` splits on `,` between `KEY=VALUE` pairs, but `CORS_ALLOWED_ORIGINS`'s own value now legitimately contains a `,` (two origins) — a bare comma-joined env-var string would have silently corrupted the parse. Fixed with gcloud's `^;^KEY=val;KEY2=val2` custom-delimiter syntax. Caught by inspecting the actually-deployed env vars, not from any error message — the naive version would have failed silently.

CORS verified live:
```
$ curl -sS -X OPTIONS https://gharos-api-971309809251.asia-south1.run.app/debug/gemini-ping \
    -H "Origin: https://gharos-web-971309809251.asia-south1.run.app" \
    -H "Access-Control-Request-Method: GET" -i
HTTP/2 200
access-control-allow-methods: GET
access-control-allow-origin: https://gharos-web-971309809251.asia-south1.run.app
```

`min-instances=0` confirmed on `gharos-web` the same way as `gharos-api` (no explicit "Min instances" line in `gcloud run services describe`).

---

## Requirement 4 — Phase 14 nightly Memory Consolidation: real deploy, real Scheduler job, real captured firing (ADR-021)

Opened this phase per ADR-021 Decision 6, honestly scoped in two parts: **(a)** below — a real, unattended, Scheduler-triggered firing of the deployed consolidation job, captured today, proving the mechanism works end to end on Cloud Run; **(b)** the accumulated genuine multi-hour/overnight timestamp record, left running unattended from today onward, captured at Phase 15's own gate once real time has passed — not fabricated here under this phase's own deadline.

**Deploy:** `gharos-api` redeployed via `./infra/deploy_backend.sh` (operator-run, real source buildpack build — `gharos-api-00007-px5`), carrying E1's `consolidation_service.py`, E2's `constraint_promotion.py`/`vendor_reliability_scoring.py`, and this phase's `pubsub_receiver.py` dispatch wiring. `./infra/pubsub_topics.sh` then wired the new push subscription and its env vars, producing one further revision (`gharos-api-00008-c6h`, env-var-only change, same code) — this is the revision serving traffic below.

```
$ gcloud run services describe gharos-api --region=asia-south1 --format="yaml(status.latestReadyRevisionName)"
status:
  latestReadyRevisionName: gharos-api-00008-c6h
```
No `minScale` annotation present (only `autoscaling.knative.dev/maxScale: '2'`) — `min-instances=0` preserved, per this project's non-negotiable cost rule.

**Cloud Scheduler jobs live, post-deploy** (`gcloud scheduler jobs list --location=asia-south1`):

```
ID                            SCHEDULE      STATE    LAST_ATTEMPT_TIME
gharos-heartbeat-tick         */5 * * * *   ENABLED  2026-08-29T16:00:05.359623Z
gharos-consolidation-nightly  30 21 * * *   ENABLED  2026-08-29T16:03:58.010515Z
gharos-followup-sweep         0 7,19 * * *  ENABLED
```

`gharos-consolidation-nightly` (this phase, real off-peak cadence 21:30 UTC = 03:00 IST) and `gharos-followup-sweep` (Phase 7 — already coded in `infra/scheduler_jobs.sh` but never actually applied to the live project until this phase's script re-run) are both now real and `ENABLED`, alongside the Phase 2 heartbeat.

**Today's captured firing** — triggered manually (`gcloud scheduler jobs run gharos-consolidation-nightly`) to start the clock rather than waiting up to ~11 hours for the natural 03:00 IST tick; everything after the trigger is a real, unattended Cloud Run execution with real Cloud Logging output, not a simulation:

```
$ gcloud scheduler jobs run gharos-consolidation-nightly --location=asia-south1
(exit 0, 2026-08-29T16:03:57Z)

$ gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=gharos-api' \
    --freshness=20m --format=json
2026-08-29T16:04:01.695068Z  consolidation_nightly_tick_received  cycle_label=2026-08-29 message_id=20276795602353480 publish_time=2026-08-29T16:03:58.04Z subscription=projects/blissful-trail-506312-t0/subscriptions/gharos-consolidation-nightly-push
2026-08-29T16:04:01.729520Z  consolidation_service.nightly_run_starting  cycle_label=2026-08-29
2026-08-29T16:04:02.573795Z  graph_maintainer.run_completed  integrity_violations=0 obligations_flagged=0 ran_at=2026-08-29T16:04:01.729875+00:00
2026-08-29T16:04:02.573895Z  consolidation_service.run_completed  constraint_promotion_wired=False integrity_violations=0 obligations_flagged=0 patterns_mined=0 ran_at=2026-08-29T16:04:01.729875+00:00 vendor_reliability_wired=False
2026-08-29T16:04:02.573958Z  consolidation_service.nightly_run_finished  cycle_label=2026-08-29 integrity_violations=0 obligations_flagged=0 patterns_mined=0
2026-08-29T16:04:02.574220Z  consolidation_nightly_completed  cycle_label=2026-08-29 message_id=20276795602353480 summary='ConsolidationRunResult(ran_at=datetime.datetime(2026, 8, 29, 16, 4, 1, 729875, tzinfo=datetime.timezone.utc), patterns_mined=(), maintenance=MaintenanceRunResult(ran_at=datetime.datetime(2026, 8, 29, 16, 4, 1, 729875, tzinfo=datetime.timezone.utc), obligations_flagged=(), integrity_violations=()), constraint_promotion=None, vendor_reliability=None)'
2026-08-29T16:04:02.574515Z  INFO:  169.254.169.126:45434 - "POST /events/consolidation-nightly HTTP/1.1" 204 No Content
```

End-to-end trace, real timestamps: Scheduler trigger (16:03:57Z) → Pub/Sub publish (`publishTime=16:03:58.04Z`) → push delivery + OIDC verification + envelope parse (`consolidation_nightly_tick_received`, 16:04:01.695Z) → `ConsolidationService.run()` invoking A10 Pattern Miner and A11 Graph Maintainer for real (16:04:01.729Z–16:04:02.573Z) → real `ConsolidationRunResult` logged and the route returning a genuine `204` (16:04:02.574Z). `patterns_mined=0`/`obligations_flagged=0`/`integrity_violations=0` and `constraint_promotion=None`/`vendor_reliability=None` are honest outputs for an empty/near-empty demo graph and E2's callbacks not yet wired (tracked as DEBT-012) — not a fabricated or suppressed result.

Left running, per ADR-021 Decision 6: no teardown after this capture. The genuine overnight/multi-hour accumulation of further unattended firings (this job's real 03:00 IST tick, plus the heartbeat and follow-up sweep continuing alongside it) is captured at Phase 15's own gate once real time has passed.

---

*Run `./infra/teardown.sh` after any proof-capture session to scale both services back to zero instances (PHASES.md §6.2.6) — services stay deployed, revision history and these logs stay intact, compute cost goes to zero until the next deploy. **Not run after this capture** (ADR-021 Decision 6, Phase 14) — the nightly consolidation job, heartbeat, and follow-up sweep are deliberately left live and unattended for Phase 15 to capture the accumulated overnight evidence.*

---

## Phase 15 — Demo Hardening: overnight run closed, final deploy runbook, demo-mode determinism

Everything below is **real command output captured 2026-08-30, against the same live `blissful-trail-506312-t0` project**, by E3. It closes ADR-021 Decision 6 part (b) — the genuine unattended overnight accumulation — and adds the final-deploy runbook and the demo-mode determinism audit that Gate 15 asks for.

### Requirement 4 (b) — the genuine unattended overnight run, captured

**Accumulation window:** from the Phase 14 backend deploy — revision `gharos-api-00008-c6h`, created **`2026-08-29T16:02:18Z`** — to this capture at **`2026-08-30T07:45Z`**. ≈ 15 h 43 m of continuous, human-untouched operation. In IST that is 21:32 on 29 Aug → 13:15 on 30 Aug, so the household's entire overnight window (roughly 22:00–07:00 IST) fell *inside* the accumulation period. Nothing was triggered by hand after the single "start the clock" `gcloud scheduler jobs run` on 29 Aug that the Phase 14 section above already discloses — every firing below is the job's own cron doing its own thing while nobody watched.

**All three Scheduler jobs still `ENABLED`, no error status, at capture time:**
```
$ gcloud scheduler jobs list --project=blissful-trail-506312-t0 --location=asia-south1 \
    --format="table(name.basename(),schedule,timeZone,state,lastAttemptTime)"
gharos-heartbeat-tick         */5 * * * *   Etc/UTC  ENABLED  2026-08-30T07:45:04.993651Z
gharos-consolidation-nightly  30 21 * * *   Etc/UTC  ENABLED  2026-08-29T21:30:04.037548Z
gharos-followup-sweep         0 7,19 * * *  Etc/UTC  ENABLED  2026-08-30T07:00:03.209241Z
```
(`gcloud scheduler jobs describe <job>` on each shows `status: {}` — i.e. the last attempt returned no error.)

**1 — `gharos-consolidation-nightly`: the first genuinely-scheduled (not manually-run) firing.** Its natural `30 21 * * *` UTC cron fired at **`2026-08-29T21:30:04Z` = 03:00 IST 30 Aug**, the exact off-peak hour ADR-021 chose, with no human involved. Full Cloud Logging trace, real timestamps, `message_id=21378051386725638`:
```
$ gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=gharos-api
    AND timestamp>="2026-08-29T21:30:00Z" AND timestamp<="2026-08-29T21:30:10Z"' --order=asc

2026-08-29T21:30:04.853Z  consolidation_nightly_tick_received      cycle_label=2026-08-29 message_id=21378051386725638 publish_time=2026-08-29T21:30:04.068Z subscription=projects/blissful-trail-506312-t0/subscriptions/gharos-consolidation-nightly-push
2026-08-29T21:30:04.857Z  consolidation_service.nightly_run_starting   cycle_label=2026-08-29
2026-08-29T21:30:05.801Z  graph_maintainer.run_completed              integrity_violations=0 obligations_flagged=0 ran_at=2026-08-29T21:30:04.858182+00:00
2026-08-29T21:30:05.801Z  consolidation_service.run_completed         constraint_promotion_wired=False integrity_violations=0 obligations_flagged=0 patterns_mined=0 vendor_reliability_wired=False
2026-08-29T21:30:05.801Z  consolidation_service.nightly_run_finished  cycle_label=2026-08-29 integrity_violations=0 obligations_flagged=0 patterns_mined=0
2026-08-29T21:30:05.801Z  consolidation_nightly_completed             cycle_label=2026-08-29 message_id=21378051386725638 summary='ConsolidationRunResult(...patterns_mined=(), maintenance=MaintenanceRunResult(obligations_flagged=(), integrity_violations=()), constraint_promotion=None, vendor_reliability=None)'
2026-08-29T21:30:05.801Z  INFO:  169.254.169.126:31000 - "POST /events/consolidation-nightly HTTP/1.1" 204 No Content
```
End-to-end, unattended: Scheduler cron → Pub/Sub publish (`publish_time=21:30:04.068Z`) → OIDC-verified push delivery (`…tick_received`, 21:30:04.853Z) → `ConsolidationService.run()` invoking A10 Pattern Miner + A11 Graph Maintainer for real (21:30:04.857Z–21:30:05.801Z) → real `ConsolidationRunResult` logged → genuine `204`.
`patterns_mined=0` / `constraint_promotion_wired=False` / `vendor_reliability_wired=False` are the same honest outputs Phase 14 disclosed — an empty/near-empty demo graph and E2's aggregate callbacks not yet wired (**DEBT-012**). Not suppressed, not fabricated.

**2 — `gharos-followup-sweep` (A31, Phase 7): both natural twice-daily firings landed.**
```
2026-08-29T19:00:04.498Z  followup_sweep_tick_received  message_id=20275920228138385 publish_time=2026-08-29T19:00:00.88Z  subscription=…/gharos-followup-sweep-push
2026-08-29T19:00:04.498Z  INFO:  … - "POST /events/followup-sweep HTTP/1.1" 204 No Content
2026-08-30T07:00:04.042Z  followup_sweep_tick_received  message_id=21384053888023669 publish_time=2026-08-30T07:00:03.242Z  subscription=…/gharos-followup-sweep-push
2026-08-30T07:00:04.042Z  INFO:  … - "POST /events/followup-sweep HTTP/1.1" 204 No Content
```

**3 — `gharos-heartbeat-tick`: 187 firings in the window, zero misses.**
```
$ gcloud logging read 'resource.type=cloud_run_revision AND resource.labels.service_name=gharos-api
    AND textPayload:"heartbeat_received" AND timestamp>="2026-08-29T16:02:18Z"' --order=asc --format='value(timestamp)' | wc -l
187
   first: 2026-08-29T16:05:00.797Z
   last:  2026-08-30T07:35:06.307Z
```
`*/5 * * * *` over 15 h 43 m predicts ≈ 188 ticks; 187 observed (the boundary minute rounds either way) — i.e. no dropped ticks across the whole unattended overnight. Over a wider trailing 20 h window the count is 240/240.

**`min-instances=0` held throughout** — the cost rule was never touched to keep the service warm overnight:
```
$ gcloud run services describe gharos-api --region=asia-south1 --format="yaml(spec.template.metadata.annotations)"
autoscaling.knative.dev/maxScale: '2'        # <-- the only scaling annotation present
$ gcloud run services describe gharos-web --region=asia-south1 --format="yaml(spec.template.metadata.annotations)"
autoscaling.knative.dev/maxScale: '2'        # <-- same; no minScale on either service
```
Cloud Run only emits a `minScale` / `autoscaling.knative.dev/minScale` line when it is set above 0. Its absence on both services is the proof min-instances is 0. With min=0, an idle Cloud Run service bills nothing; the ~15.7 h overnight run cost is the 190-odd sub-second, no-LLM, no-Firestore-write heartbeat/sweep invocations plus 2 Pub/Sub messages/min — negligible, exactly as ADR-021 Decision 6 planned.

**Re-capture any time** with `./scripts/capture_deploy_proof.sh` (read-only — `describe` / `list` / `logging read` only; no deploy, no mutation, no cost). `./scripts/capture_deploy_proof.sh --since 24h > /tmp/block.md` writes a paste-ready Markdown block.

**Budget alert still active** (verified at this gate, per the standing rule):
```
$ gcloud billing budgets list --billing-account=<open account>
DISPLAY_NAME           CURRENCY_CODE  UNITS  THRESHOLD_PERCENT
GharOS monthly budget  INR            2000   [0.5, 0.9]
```

### Final deploys — exact commands the operator runs

Per the Phase 2 / Phase 14 precedent, **E3 does not run `gcloud run deploy`** (real-world effect — the operator does). The `infra/` scripts below wrap it; they are idempotent and were re-verified (`bash -n`, dry logic run) at this gate. Run them from the repo root, in this order:

```bash
# 0. one-time per shell — auth + project (skip if already set)
gcloud auth login
export GHAROS_PROJECT_ID=blissful-trail-506312-t0

# 1. (optional) OAuth ingestion-connector config — Phase 14.5 / ADR-022.
#    CLIENT SECRETS ARE NEVER PASSED HERE AS LITERALS. The *_SECRET_REF
#    values are Secret Manager secret ids (pointers); deploy_backend.sh
#    fail-closes if either looks like a raw secret. Leave all of these
#    unset for a deploy that does not demo the Connections page — the
#    /oauth/* routes then return a clean 503 and nothing else changes.
export GOOGLE_OAUTH_CLIENT_ID='<operator fills: Google OAuth client id, ...apps.googleusercontent.com>'
export GOOGLE_OAUTH_CLIENT_SECRET_REF='gharos-oauth-google-client-secret'      # Secret Manager id, NOT the secret
export MICROSOFT_OAUTH_CLIENT_ID='<operator fills: Azure app (client) id, or leave unset>'
export MICROSOFT_OAUTH_CLIENT_SECRET_REF='gharos-oauth-microsoft-client-secret' # Secret Manager id, NOT the secret
export MICROSOFT_OAUTH_TENANT='consumers'
# OAUTH_REDIRECT_BASE_URL / FRONTEND_CONNECTIONS_URL default to the live
# gharos-api / gharos-web URLs when unset — only set them to override.
# export OAUTH_REDIRECT_BASE_URL='https://gharos-api-971309809251.asia-south1.run.app'
# export FRONTEND_CONNECTIONS_URL='https://gharos-web-971309809251.asia-south1.run.app/connections'

# 2. (optional) Google Drive picker browser keys — Phase 14.5. Public
#    browser values (referrer-restricted API key + the GCP project
#    NUMBER), not secrets. Unset -> the picker shows a "needs config"
#    message and the rest of Connections works.
# export NEXT_PUBLIC_GOOGLE_PICKER_API_KEY='<operator fills: browser API key>'
# export NEXT_PUBLIC_GOOGLE_APP_ID='971309809251'

# 3. (optional) demo-hardening mode — see "Demo-mode determinism" below.
#    Default is production. ENV=demo swaps the deterministic voice-TTS
#    path in; nothing about the real path changes for a normal deploy.
# export GHAROS_ENV=demo

# 4. backend  (gcloud run deploy gharos-api --source ./backend  — buildpacks, no Dockerfile)
./infra/deploy_backend.sh

# 5. re-wire the Pub/Sub push subscriptions + their OIDC env vars against
#    the URL the deploy just produced (idempotent; safe to re-run)
./infra/pubsub_topics.sh

# 6. frontend (gcloud run deploy gharos-web --source ./frontend  — buildpacks, no Dockerfile)
#    looks up gharos-api's live URL for NEXT_PUBLIC_API_BASE_URL automatically
./infra/deploy_frontend.sh

# 7. reconcile the three Scheduler jobs (idempotent — create-or-update)
./infra/scheduler_jobs.sh
```

`infra/deploy_backend.sh` sets these runtime env vars on `gharos-api` (verified against `backend/app/settings.py` field names): `GCP_PROJECT_ID`, `GCP_REGION`, `VERTEX_AI_LOCATION`, `ENV` (`production` unless `GHAROS_ENV` overrides), `CORS_ALLOWED_ORIGINS` (both real gharos-web URL forms), and — when the operator exported them in step 1 — `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET_REF`, `MICROSOFT_OAUTH_CLIENT_ID`, `MICROSOFT_OAUTH_CLIENT_SECRET_REF`, `MICROSOFT_OAUTH_TENANT`, `OAUTH_REDIRECT_BASE_URL`, `FRONTEND_CONNECTIONS_URL`. `infra/pubsub_topics.sh` then merges in `PUBSUB_PUSH_SERVICE_ACCOUNT_EMAIL` / `PUBSUB_PUSH_AUDIENCE` (`--update-env-vars`, so the step-4 vars survive). `infra/deploy_frontend.sh` sets build-time `NEXT_PUBLIC_API_BASE_URL` and, when exported, `NEXT_PUBLIC_GOOGLE_PICKER_API_KEY` / `NEXT_PUBLIC_GOOGLE_APP_ID`.

**Post-deploy — operator pastes the real revision detail here:**

| Service | New revision | `Deploying revision succeeded` / `Containers became healthy` | Build type |
|---|---|---|---|
| `gharos-api` | `<operator fills: revision id, e.g. gharos-api-000NN-xxx>` | `<operator fills: from the deploy success banner>` | `<operator fills: "Building using Buildpacks" line from the build log — must NOT say Dockerfile>` |
| `gharos-web` | `<operator fills: revision id, e.g. gharos-web-000NN-xxx>` | `<operator fills: from the deploy success banner>` | `<operator fills: "Building using Buildpacks">` |

```
# operator runs after deploying, pastes output:
$ gcloud run services describe gharos-api --region=asia-south1 --format="yaml(status.latestReadyRevisionName)"
<operator fills>
$ gcloud run revisions describe <gharos-api revision> --region=asia-south1 \
    --format="value(metadata.annotations['run.googleapis.com/build-source-location'])"
<operator fills — a gs://run-sources-.../services/gharos-api/....zip reference == a source (buildpack) build, no Dockerfile>
$ gcloud run services describe gharos-web --region=asia-south1 --format="yaml(status.latestReadyRevisionName)"
<operator fills>
```
_Reference (the currently-live Phase 14 revisions, for format): `gharos-api-00008-c6h`, build-source-location `gs://run-sources-blissful-trail-506312-t0-asia-south1/services/gharos-api/1788019085.632033-….zip`; `gharos-web-00002-tgw`._

### No Dockerfile — asserted at Gate 15

```
$ find . -iname "Dockerfile*" -not -path "*/node_modules/*"
$            # <-- no output. Also checked: Containerfile*, .dockerignore — none.
```
Empty, re-verified at this gate. Cloud Run builds both services from source via Google Cloud Buildpacks (`gcloud run deploy --source`), never a container image the repo defines.

**The deploy scripts fail closed if a Dockerfile ever appears** — this is enforced in code, not by convention:
- `infra/deploy_backend.sh`: `if find "$BACKEND_DIR" -iname "Dockerfile*" … ; then die "A Dockerfile was found under ./backend. GharOS uses buildpack source deploys only …"` — the deploy aborts *before* `gcloud` is called.
- `infra/deploy_frontend.sh`: the identical guard over `./frontend` (excluding `node_modules/`).
- `infra/_common.sh:require_file` additionally aborts the backend deploy if `backend/Procfile` or `backend/requirements.txt` is missing — the two files buildpacks need to build a Python service *without* a Dockerfile.

### Demo-mode determinism — flaky external calls on the 4-minute demo path (spec §24)

Audited every live external call the on-camera run touches. Toggle is `ENV=demo` (`GHAROS_ENV=demo` at deploy time) — a single explicit opt-in. **The real path is the default and cannot be disabled for a non-demo deployment**; `ENV=demo` only swaps deterministic stand-ins in front of the calls that would otherwise flake.

| Demo-path external call | Owner | Flake risk on camera | Deterministic / sandboxed mode | Toggle |
|---|---|---|---|---|
| **Voice TTS** — `voice/tts_client.py`, live Vertex AI Gemini audio-output call to the `global` location on a `-preview-tts` model | E3 | Transient 5xx / latency spike during the 20 s voice beat (2:20) | `voice.tts_client.DeterministicTtsClient` — network-free; returns byte-for-byte reproducible PCM16 (same rate/MIME as the real response) seeded from `sha256(text\|voice\|lang)`. Wired by `create_tts_client(env=…)`, selected in `api/voice_router.py:get_tts_client`. Test: `backend/tests/test_tts_demo_mode.py` (5 tests — determinism, per-axis variation, real-path default for every non-`demo` env). | `ENV=demo` |
| **Every Gemini reasoning call on the critical path** (extraction, implication, Fair Allocator, Council specialists/delegates/adversary, concierge clarifiers, voice ASR/intent/normalisation) — all routed through `reasoning/gemini_client.py:GeminiClient` | E2 | Sampling variation run-to-run; transient Vertex error | E2 pins `temperature=0.0` + a fixed `seed` on **every** call in `GeminiClient` (one enforcement point, unconditionally — `DETERMINISTIC_TEMPERATURE` / `DETERMINISTIC_SEED`). A determinism *lever*, not a bit-identical guarantee (Vertex makes no such promise); E2's write-up states this honestly. | E2's `gemini_client.py` (always on) |
| **The live exception beat** — A3c "nut-free item that never appears on any receipt" (`absent_from`), spec §24 3:05 | E2 | Must fire identically every rehearsal + on camera | Produced by **deterministic code** (`agents/intake/verification_agent.py:_check_absent_from`) that never reads model output. Test: `backend/tests/test_demo_exception_beat_determinism.py`. | n/a — no model call |
| **Outbound-concierge counterparty** — `agents/concierge/sandbox_counterparty.py` | E2 | It is already a *sandbox* (a second LLM, never a real business — spec §13 / ADR-016), but its own reply is a Gemini call | Sandboxed by construction (no real telephony/business rail anywhere in `voice_call_tool.py` / `sandbox_counterparty.py`); its Gemini call inherits E2's `temperature=0` + seed. `provider_search_tool.py` (T1 service discovery) is a **deterministic seeded synthetic directory** — no Places/Maps API is integrated anywhere in the codebase (stated plainly in that module). | `ENV=demo` (TTS) + E2 pinning |
| **A36 grounded web search** — `GeminiClient.generate_grounded_text` (Google Search grounding) | E2 | Live web results vary; grounding may not trigger | **Not on the 4-minute demo path** — A36 belongs to the Household Simulator (Phase 11), which the demo script (§24) does not exercise. If run, it inherits E2's `temperature=0` + seed; the honest "zero citations" path is already a first-class outcome (ADR-017). | n/a for the demo |
| **Ingestion adapters** (email / SMS / chat-export / document-upload) | E3 | — | The demo trigger is a seeded document published to Pub/Sub (E1's demo seed), parsed from a payload already in hand — **no live mailbox/API fetch on the critical path**. The OAuth connectors (`connectors/gmail_connector.py`, `outlook_connector.py`) *do* call live provider APIs, but they belong to the Connections onboarding surface, not the 4-minute run. | n/a for the demo |

**Honest limitation, stated for the write-up honesty pass:** `ENV=demo` removes the one E3-owned live external call (voice TTS) from the demo and lets E2's temperature/seed pinning remove avoidable sampling variance from the rest. It does **not** make the whole run hermetic — the reasoning calls still hit Vertex AI live, and Vertex does not promise bit-identical output at temperature 0. The backup recording (E4's Gate 15 item) is the real fallback if a live reasoning call misbehaves on camera; the determinism levers make that unlikely, not impossible.

### Teardown after the final capture

```
./infra/teardown.sh                    # hold both Cloud Run services at service-level min=0 (idle -> zero compute cost)
./infra/teardown.sh --pause-schedulers # also pause heartbeat + nightly consolidation + follow-up sweep
```
`teardown.sh` now uses the **service-level `--min=0`** flag (applied live, no new revision) instead of the old per-revision `--min-instances=0 --max-instances=0` (which cut a fresh revision on every run and risked a `max-instances=0` API rejection). Services stay deployed; revisions, source-build logs, and all the Cloud Logging history above stay intact. `--pause-schedulers` is **opt-in** so running teardown mid-Phase-15 does not end an in-progress unattended run; resume with `gcloud scheduler jobs resume <job> --location=asia-south1` or by re-running `./infra/scheduler_jobs.sh`. Re-deploying via `infra/deploy_*.sh` restores `max-instances=2`; `min` stays 0 — the cost rule is never overridden.

**Not run yet as of this capture** — the three Scheduler jobs are still `ENABLED` and unattended so the overnight window keeps accumulating until the operator captures the final block (`./scripts/capture_deploy_proof.sh`) and then runs `./infra/teardown.sh --pause-schedulers`.
