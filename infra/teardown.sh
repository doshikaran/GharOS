#!/usr/bin/env bash
# GharOS — infra/teardown.sh
#
# PHASES.md §6.2.6: "infra/teardown.sh scales to zero; run after every
# proof capture." This is a standing cost-control rule, not a one-off
# script — run it every time after grabbing screenshots/logs for
# docs/DEPLOYMENT_PROOF.md.
#
# What "scale to zero" means here, precisely:
#   - Both Cloud Run services (gharos-api, gharos-web) stay DEPLOYED.
#     Revision history, source-build logs, and the Cloud Logging trail all
#     stay intact — docs/DEPLOYMENT_PROOF.md keeps working.
#   - Their minimum instance count is pinned to 0 (the cost lever). With
#     min=0, an idle Cloud Run service bills nothing — Cloud Run only
#     charges for request-processing time. This is already the deploy
#     default (infra/deploy_backend.sh / deploy_frontend.sh refuse to set
#     it otherwise); teardown re-asserts it via the SERVICE-level `--min`
#     flag, which takes effect immediately WITHOUT cutting a new revision
#     (unlike the per-revision `--min-instances`, which would).
#
# Optional, opt-in with `--pause-schedulers`:
#   - Pauses the three Cloud Scheduler jobs (heartbeat every 5 min,
#     nightly consolidation, follow-up sweep) so nothing wakes gharos-api
#     after the capture. Left OFF by default so running this mid-Phase-15
#     does NOT end the genuine unattended overnight run that Gate 15 and
#     ADR-021 depend on. Resume them with:
#       gcloud scheduler jobs resume <job> --location=asia-south1
#     or just re-run ./infra/scheduler_jobs.sh (create/update) followed by
#     `gcloud scheduler jobs resume` for any that were paused.
#
# Idempotent: safe to run when a service or job doesn't exist yet (skipped
# with a note) or is already scaled down / already paused (no-op).
#
# Usage:
#   ./infra/teardown.sh
#   ./infra/teardown.sh --pause-schedulers

set -euo pipefail
readonly SCRIPT_PATH="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

PAUSE_SCHEDULERS=0
for arg in "$@"; do
  case "$arg" in
    --pause-schedulers) PAUSE_SCHEDULERS=1 ;;
    -h | --help)
      grep -E '^#( |$)' "$SCRIPT_PATH" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *) die "unknown argument: $arg (accepted: --pause-schedulers)" ;;
  esac
done

echo "=================================================================="
echo " GharOS — teardown (hold Cloud Run services at min-instances=0)"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Nothing to tear down."
log "Project: $project_id  Region: $GHAROS_REGION"

readonly SCHEDULER_JOBS=(
  "gharos-heartbeat-tick"
  "gharos-consolidation-nightly"
  "gharos-followup-sweep"
)

scale_to_zero() {
  local service="$1"
  if ! gcloud run services describe "$service" \
      --project "$project_id" --region "$GHAROS_REGION" >/dev/null 2>&1; then
    log "  $service: not deployed — nothing to scale down."
    return 0
  fi

  # `--min` (service-level) not `--min-instances` (per-revision): the
  # service-level flag is applied dynamically to the live service without
  # cutting a new revision, so teardown never pollutes revision history or
  # risks an immutable-field redeploy. `--max` is deliberately left
  # untouched — infra/deploy_*.sh own it (max-instances=2), and Cloud Run
  # will not create any instance anyway while there is no traffic and
  # min=0.
  log "  $service: pinning service-level min instances to 0..."
  gcloud run services update "$service" \
    --project "$project_id" \
    --region "$GHAROS_REGION" \
    --min=0 \
    --quiet >/dev/null
  log "  $service: min=0 confirmed (idle -> zero compute cost; service stays reachable, revisions intact)."
}

pause_scheduler_job() {
  local job="$1"
  if ! gcloud scheduler jobs describe "$job" \
      --project "$project_id" --location "$GHAROS_REGION" >/dev/null 2>&1; then
    log "  $job: not found — skipping."
    return 0
  fi
  local state
  state="$(gcloud scheduler jobs describe "$job" \
    --project "$project_id" --location "$GHAROS_REGION" --format='value(state)' 2>/dev/null || true)"
  if [[ "$state" == "PAUSED" ]]; then
    log "  $job: already PAUSED — no-op."
    return 0
  fi
  log "  $job: pausing (was $state)..."
  gcloud scheduler jobs pause "$job" \
    --project "$project_id" --location "$GHAROS_REGION" --quiet >/dev/null
  log "  $job: PAUSED. Resume: gcloud scheduler jobs resume $job --location=$GHAROS_REGION"
}

log "Scaling GharOS Cloud Run services to zero..."
scale_to_zero "$GHAROS_API_SERVICE"
scale_to_zero "$GHAROS_WEB_SERVICE"

if [[ "$PAUSE_SCHEDULERS" -eq 1 ]]; then
  log "Pausing Cloud Scheduler jobs (--pause-schedulers given)..."
  for job in "${SCHEDULER_JOBS[@]}"; do
    pause_scheduler_job "$job"
  done
else
  log "Cloud Scheduler jobs left running (pass --pause-schedulers to pause them)."
  log "  Note: while running, the heartbeat wakes gharos-api ~every 5 min for a few ms"
  log "  (one Pub/Sub publish + one min=0 invocation, no LLM call, no Firestore write) —"
  log "  this is the deliberate, cost-negligible state ADR-021's overnight run relies on."
fi

echo "=================================================================="
log "Teardown complete."
log "Both services (where deployed) are at service-level min=0 — idle cost is zero."
log "Revisions, source-build logs, and Cloud Logging history are preserved for docs/DEPLOYMENT_PROOF.md."
log "To resume serving under load, re-run ./infra/deploy_backend.sh / ./infra/deploy_frontend.sh"
log "(they restore max-instances=2; min stays 0 — cost control is never overridden)."
echo "=================================================================="
