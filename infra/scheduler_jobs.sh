#!/usr/bin/env bash
# GharOS — infra/scheduler_jobs.sh
#
# STUB for Phase 0 (PHASES.md §0.C repo structure lists this file; content
# is filled in from Phase 1 onward per spec §25 build sequencing: monthly
# salary/dues cycles, off-peak consolidation, follow-up cadence, call
# retries — spec §20, §21.3).
#
# Every job here publishes a contracts.events.ScheduledTickPayload onto a
# Pub/Sub topic (see infra/pubsub_topics.sh — the "scheduled_tick" inbound
# topic) via Cloud Scheduler's Pub/Sub target. Cloud Scheduler is the
# trigger; the Pub/Sub topic + Cloud Run subscriber does the work — no
# Cloud Scheduler job should ever call an HTTP endpoint directly for a
# graph-mutating cycle, so a missed ack doesn't silently drop the job.
#
# Idempotent: `gcloud scheduler jobs create` fails if the job already
# exists; this script checks first and uses `update` on existing jobs so
# re-running is always safe.
#
# Usage (once Phase 1+ fills in the TODO list below):
#   ./infra/scheduler_jobs.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

echo "=================================================================="
echo " GharOS — Cloud Scheduler jobs (Phase 1+ content, Phase 0 skeleton)"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id  Region: $GHAROS_REGION"

# TODO(Phase 1+, E3): each entry is "name|cron|topic|cycle_label_hint".
# Fill in against contracts/events.py:ScheduledTickPayload once the
# consuming subsystems (Ledger payroll/dues, Consolidation, Concierge
# follow-up/retry) exist. Examples anticipated by spec §20/§21.3:
#   gharos-monthly-payroll       | 0 6 1 * *   | gharos-inbound-scheduled-tick | monthly payroll cycle
#   gharos-monthly-dues          | 0 6 1 * *   | gharos-inbound-scheduled-tick | monthly dues cycle
#   gharos-nightly-consolidation | 0 3 * * *   | gharos-inbound-scheduled-tick | off-peak graph consolidation
#   gharos-followup-cadence      | 0 */6 * * * | gharos-inbound-scheduled-tick | concierge follow-up sweep
#   gharos-call-retry-ladder     | */15 * * * *| gharos-inbound-scheduled-tick | outbound call fallback ladder
SCHEDULER_JOBS=(
  # "gharos-monthly-payroll|0 6 1 * *|gharos-inbound-scheduled-tick|monthly-payroll"
  # ...
)

if [[ ${#SCHEDULER_JOBS[@]} -eq 0 ]]; then
  log "No scheduler jobs defined yet — this is expected in Phase 0."
  log "Phase 1+ fills in SCHEDULER_JOBS above as consuming subsystems land."
  exit 0
fi

for entry in "${SCHEDULER_JOBS[@]}"; do
  IFS='|' read -r name cron topic cycle_hint <<<"$entry"

  message_body="{\"job_name\":\"${name}\",\"cycle_label\":\"${cycle_hint}\"}"

  if gcloud scheduler jobs describe "$name" \
      --project "$project_id" --location "$GHAROS_REGION" >/dev/null 2>&1; then
    log "  updating: $name"
    gcloud scheduler jobs update pubsub "$name" \
      --project "$project_id" \
      --location "$GHAROS_REGION" \
      --schedule "$cron" \
      --topic "$topic" \
      --message-body "$message_body" \
      --quiet
  else
    log "  creating: $name"
    gcloud scheduler jobs create pubsub "$name" \
      --project "$project_id" \
      --location "$GHAROS_REGION" \
      --schedule "$cron" \
      --topic "$topic" \
      --message-body "$message_body" \
      --quiet
  fi
done

echo "=================================================================="
log "Cloud Scheduler jobs reconciled for project $project_id."
echo "=================================================================="
