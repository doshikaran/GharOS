#!/usr/bin/env bash
# GharOS — infra/scheduler_jobs.sh
#
# PHASES.md Phase 2 work item ("Cloud Scheduler job publishing a heartbeat
# event"). Creates the Cloud Scheduler job `gharos-heartbeat-tick`, that
# publishes a `contracts.events.ScheduledTickPayload`-shaped JSON message
# directly onto the `gharos-heartbeat` Pub/Sub topic
# (`infra/pubsub_topics.sh`) via Cloud Scheduler's native Pub/Sub target —
# Cloud Scheduler never calls an HTTP endpoint directly for this (see the
# rationale in the header this file replaces: a missed ack on a direct HTTP
# call silently drops the job; going through Pub/Sub means retry/redelivery
# is Pub/Sub's job, and the receiver at `POST /events/heartbeat`
# (`backend/app/api/pubsub_receiver.py`) never needs to distinguish "Cloud
# Scheduler is down" from "my endpoint is down").
#
# Cadence: every 5 minutes (`*/5 * * * *`). Chosen over a longer interval
# (e.g. every 10) because Phase 2's only job here is proving the unattended
# Scheduler -> Pub/Sub -> Cloud Run round trip exists and stays alive — a
# tighter cadence produces more Cloud Logging evidence per hour of
# `docs/DEPLOYMENT_PROOF.md`'s "genuine unattended overnight run" artifact
# (spec §21.3) without meaningful cost: each tick is one Pub/Sub publish
# plus one `--min-instances=0` Cloud Run invocation that returns in
# milliseconds with no LLM call and no Firestore write (spec §6.2,
# `receive_heartbeat` — Layer 0, not a T-tiered tool call).
#
# Phase 7 adds `gharos-followup-sweep` (A31 Follow-up/Persistence, twice
# daily). Phase 14 adds `gharos-consolidation-nightly` (Memory
# Consolidation, ADR-021, once daily off-peak) — see that job's own block
# below for its cadence rationale. That is the full roster this file's own
# original header anticipated ("Phase 7/14 jobs... get their own, far
# coarser cadences when those subsystems exist to consume them") — three
# jobs total, still within Cloud Scheduler's free tier (3 jobs/month).
#
# Idempotent: checks for the job before creating it, and uses `update` on an
# existing job so re-running (e.g. after the topic name or schedule
# changes) is always safe — matching infra/setup_gcp.sh's convention.
#
# Usage:
#   ./infra/scheduler_jobs.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

echo "=================================================================="
echo " GharOS — Cloud Scheduler jobs (heartbeat, follow-up sweep, nightly consolidation)"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id  Region: $GHAROS_REGION"

readonly HEARTBEAT_TOPIC="gharos-heartbeat"
readonly HEARTBEAT_JOB_NAME="gharos-heartbeat-tick"
readonly HEARTBEAT_CRON="*/5 * * * *"
readonly HEARTBEAT_CYCLE_LABEL="heartbeat"

# PHASES.md Phase 7, A31 Follow-up/Persistence — "far coarser cadences"
# than the heartbeat, per this file's own header comment written back in
# Phase 2 anticipating exactly this job. Twice a day (07:00 and 19:00 IST)
# is enough to make "re-contact on cadence; escalate after N" real without
# creating meaningful Cloud Run/Vertex AI spend (spec §6.2 cost
# discipline) — open claims and vendor requests are not a sub-hour-latency
# problem the way a live demo heartbeat is.
readonly FOLLOWUP_SWEEP_TOPIC="gharos-followup-sweep"
readonly FOLLOWUP_SWEEP_JOB_NAME="gharos-followup-sweep"
readonly FOLLOWUP_SWEEP_CRON="0 7,19 * * *"
readonly FOLLOWUP_SWEEP_CYCLE_LABEL="followup-sweep"

# PHASES.md Phase 14, Memory Consolidation service (ADR-021 Decisions 1-3)
# — this file's own header comment, written back in Phase 2, named this
# exact job ("nightly consolidation") as one of the "far coarser cadences"
# to add once the subsystem exists to consume it. It now does
# (`app.graph.consolidation_service`, E1, landing in parallel this phase).
#
# Cadence: 21:30 UTC daily = 03:00 IST — chosen, not copied from the
# followup-sweep cadence above, for reasons specific to this job:
#   - Genuinely off-peak for an Indian household: 03:00 IST sits in the
#     middle of the household's overnight low-activity window (no member
#     is plausibly dictating new intentions, uploading documents, or
#     placing/receiving calls at that hour), unlike 07:00/19:00 IST
#     (follow-up sweep's cadence), which are deliberately chosen to be
#     NEAR activity so a human sees a fresh follow-up outcome soon after
#     it runs.
#   - A pattern-mining/graph-maintenance pass (A10, A11) reads across the
#     WHOLE graph rather than a scoped subset — running it while the
#     household is plausibly still writing new observations (evening) or
#     about to start (early morning) risks mining over a mid-update graph
#     state; 03:00 IST minimises that overlap.
#   - Once-daily, not the heartbeat's every-5-minutes or the follow-up
#     sweep's twice-daily: promoting a pattern into a durable claim, or
#     re-deriving vendor reliability scores, is not a latency-sensitive
#     cycle the way a live demo heartbeat or an open-claim follow-up is
#     (PHASES.md §6.2 cost discipline — one Cloud Run invocation and one
#     round of Firestore reads/writes per day, not per 5 minutes).
#   - Offset (:30, not :00) from the top of the hour purely to avoid this
#     job's own Pub/Sub publish landing in the exact same minute as any
#     other project's :00-aligned cron jobs sharing the same Cloud
#     Scheduler quota — a defensive habit, not a load-bearing requirement
#     at this project's single-job-per-day volume.
readonly CONSOLIDATION_NIGHTLY_TOPIC="gharos-consolidation-nightly"
readonly CONSOLIDATION_NIGHTLY_JOB_NAME="gharos-consolidation-nightly"
readonly CONSOLIDATION_NIGHTLY_CRON="30 21 * * *"
readonly CONSOLIDATION_NIGHTLY_CYCLE_LABEL="nightly"
# `cycle_label` here is a static placeholder ("nightly"), exactly as
# $HEARTBEAT_CYCLE_LABEL is "heartbeat" above — Cloud Scheduler's Pub/Sub
# message body is baked in at job create/update time and cannot carry a
# live per-run date. `app.api.pubsub_receiver.receive_consolidation_nightly`
# derives the REAL per-run cycle label (`YYYY-MM-DD`) from Pub/Sub's own
# `publishTime` on each delivered envelope instead — see that function's
# docstring.

if ! gcloud pubsub topics describe "$HEARTBEAT_TOPIC" --project "$project_id" >/dev/null 2>&1; then
  die "Topic '$HEARTBEAT_TOPIC' does not exist yet. Run ./infra/pubsub_topics.sh first."
fi
if ! gcloud pubsub topics describe "$FOLLOWUP_SWEEP_TOPIC" --project "$project_id" >/dev/null 2>&1; then
  die "Topic '$FOLLOWUP_SWEEP_TOPIC' does not exist yet. Run ./infra/pubsub_topics.sh first."
fi
if ! gcloud pubsub topics describe "$CONSOLIDATION_NIGHTLY_TOPIC" --project "$project_id" >/dev/null 2>&1; then
  die "Topic '$CONSOLIDATION_NIGHTLY_TOPIC' does not exist yet. Run ./infra/pubsub_topics.sh first."
fi

# `contracts.events.ScheduledTickPayload` has three fields: job_name,
# scheduled_for, cycle_label. `scheduled_for` is intentionally omitted here
# — Cloud Scheduler's message body is a static string baked in at job
# create/update time, not evaluated per-tick, so it cannot carry a live
# timestamp; `receive_heartbeat` and its downstream consumers use the
# envelope's own `publishTime` (assigned by Pub/Sub at publish time, real
# per-tick) for that instead.
message_body="{\"job_name\":\"${HEARTBEAT_JOB_NAME}\",\"cycle_label\":\"${HEARTBEAT_CYCLE_LABEL}\"}"

log "Reconciling Cloud Scheduler job: $HEARTBEAT_JOB_NAME ($HEARTBEAT_CRON -> $HEARTBEAT_TOPIC)..."
if gcloud scheduler jobs describe "$HEARTBEAT_JOB_NAME" \
    --project "$project_id" --location "$GHAROS_REGION" >/dev/null 2>&1; then
  log "  updating: $HEARTBEAT_JOB_NAME"
  gcloud scheduler jobs update pubsub "$HEARTBEAT_JOB_NAME" \
    --project "$project_id" \
    --location "$GHAROS_REGION" \
    --schedule "$HEARTBEAT_CRON" \
    --topic "$HEARTBEAT_TOPIC" \
    --message-body "$message_body" \
    --quiet
else
  log "  creating: $HEARTBEAT_JOB_NAME"
  gcloud scheduler jobs create pubsub "$HEARTBEAT_JOB_NAME" \
    --project "$project_id" \
    --location "$GHAROS_REGION" \
    --schedule "$HEARTBEAT_CRON" \
    --topic "$HEARTBEAT_TOPIC" \
    --message-body "$message_body" \
    --quiet
fi

followup_message_body="{\"job_name\":\"${FOLLOWUP_SWEEP_JOB_NAME}\",\"cycle_label\":\"${FOLLOWUP_SWEEP_CYCLE_LABEL}\"}"

log "Reconciling Cloud Scheduler job: $FOLLOWUP_SWEEP_JOB_NAME ($FOLLOWUP_SWEEP_CRON -> $FOLLOWUP_SWEEP_TOPIC)..."
if gcloud scheduler jobs describe "$FOLLOWUP_SWEEP_JOB_NAME" \
    --project "$project_id" --location "$GHAROS_REGION" >/dev/null 2>&1; then
  log "  updating: $FOLLOWUP_SWEEP_JOB_NAME"
  gcloud scheduler jobs update pubsub "$FOLLOWUP_SWEEP_JOB_NAME" \
    --project "$project_id" \
    --location "$GHAROS_REGION" \
    --schedule "$FOLLOWUP_SWEEP_CRON" \
    --topic "$FOLLOWUP_SWEEP_TOPIC" \
    --message-body "$followup_message_body" \
    --quiet
else
  log "  creating: $FOLLOWUP_SWEEP_JOB_NAME"
  gcloud scheduler jobs create pubsub "$FOLLOWUP_SWEEP_JOB_NAME" \
    --project "$project_id" \
    --location "$GHAROS_REGION" \
    --schedule "$FOLLOWUP_SWEEP_CRON" \
    --topic "$FOLLOWUP_SWEEP_TOPIC" \
    --message-body "$followup_message_body" \
    --quiet
fi

consolidation_message_body="{\"job_name\":\"${CONSOLIDATION_NIGHTLY_JOB_NAME}\",\"cycle_label\":\"${CONSOLIDATION_NIGHTLY_CYCLE_LABEL}\"}"

log "Reconciling Cloud Scheduler job: $CONSOLIDATION_NIGHTLY_JOB_NAME ($CONSOLIDATION_NIGHTLY_CRON -> $CONSOLIDATION_NIGHTLY_TOPIC)..."
if gcloud scheduler jobs describe "$CONSOLIDATION_NIGHTLY_JOB_NAME" \
    --project "$project_id" --location "$GHAROS_REGION" >/dev/null 2>&1; then
  log "  updating: $CONSOLIDATION_NIGHTLY_JOB_NAME"
  gcloud scheduler jobs update pubsub "$CONSOLIDATION_NIGHTLY_JOB_NAME" \
    --project "$project_id" \
    --location "$GHAROS_REGION" \
    --schedule "$CONSOLIDATION_NIGHTLY_CRON" \
    --topic "$CONSOLIDATION_NIGHTLY_TOPIC" \
    --message-body "$consolidation_message_body" \
    --quiet
else
  log "  creating: $CONSOLIDATION_NIGHTLY_JOB_NAME"
  gcloud scheduler jobs create pubsub "$CONSOLIDATION_NIGHTLY_JOB_NAME" \
    --project "$project_id" \
    --location "$GHAROS_REGION" \
    --schedule "$CONSOLIDATION_NIGHTLY_CRON" \
    --topic "$CONSOLIDATION_NIGHTLY_TOPIC" \
    --message-body "$consolidation_message_body" \
    --quiet
fi

echo "=================================================================="
log "Cloud Scheduler jobs reconciled for project $project_id."
log "Job:      $HEARTBEAT_JOB_NAME  ($HEARTBEAT_CRON)"
log "Target:   Pub/Sub topic $HEARTBEAT_TOPIC -> push subscription -> gharos-api (see infra/pubsub_topics.sh)"
log "Job:      $FOLLOWUP_SWEEP_JOB_NAME  ($FOLLOWUP_SWEEP_CRON)"
log "Target:   Pub/Sub topic $FOLLOWUP_SWEEP_TOPIC -> push subscription -> gharos-api (see infra/pubsub_topics.sh)"
log "Job:      $CONSOLIDATION_NIGHTLY_JOB_NAME  ($CONSOLIDATION_NIGHTLY_CRON, ~03:00 IST)"
log "Target:   Pub/Sub topic $CONSOLIDATION_NIGHTLY_TOPIC -> push subscription -> gharos-api (see infra/pubsub_topics.sh)"
log "Verify:   gcloud scheduler jobs describe $HEARTBEAT_JOB_NAME --location=$GHAROS_REGION"
log "          gcloud scheduler jobs describe $FOLLOWUP_SWEEP_JOB_NAME --location=$GHAROS_REGION"
log "          gcloud scheduler jobs describe $CONSOLIDATION_NIGHTLY_JOB_NAME --location=$GHAROS_REGION"
log "          gcloud logging read 'resource.type=cloud_run_revision' --limit=5   (after a deploy + a few ticks)"
echo "=================================================================="
