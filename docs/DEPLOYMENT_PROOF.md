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
