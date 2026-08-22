#!/usr/bin/env bash
# GharOS — infra/scheduler_jobs.sh
#
# PHASES.md Phase 2 work item ("Cloud Scheduler job publishing a heartbeat
# event"). Creates one Cloud Scheduler job, `gharos-heartbeat-tick`, that
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
# (spec §21.3) without meaningful cost: Cloud Scheduler's free tier covers 3
# jobs, and each tick is one Pub/Sub publish plus one `--min-instances=0`
# Cloud Run invocation that returns in milliseconds with no LLM call and no
# Firestore write (spec §6.2, `receive_heartbeat` — Layer 0, not a T-tiered
# tool call). Phase 7/14 jobs (payroll, dues, nightly consolidation,
# follow-up sweeps) get their own, far coarser cadences when those
# subsystems exist to consume them — this file's job right now is the
# Phase 2 mechanism, not the full Phase 7/14 job roster.
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
echo " GharOS — Cloud Scheduler heartbeat job"
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

if ! gcloud pubsub topics describe "$HEARTBEAT_TOPIC" --project "$project_id" >/dev/null 2>&1; then
  die "Topic '$HEARTBEAT_TOPIC' does not exist yet. Run ./infra/pubsub_topics.sh first."
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

echo "=================================================================="
log "Cloud Scheduler heartbeat job reconciled for project $project_id."
log "Job:      $HEARTBEAT_JOB_NAME  ($HEARTBEAT_CRON)"
log "Target:   Pub/Sub topic $HEARTBEAT_TOPIC -> push subscription -> gharos-api (see infra/pubsub_topics.sh)"
log "Verify:   gcloud scheduler jobs describe $HEARTBEAT_JOB_NAME --location=$GHAROS_REGION"
log "          gcloud logging read 'resource.type=cloud_run_revision' --limit=5   (after a deploy + a few ticks)"
echo "=================================================================="
