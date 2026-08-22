#!/usr/bin/env bash
# GharOS — infra/pubsub_topics.sh
#
# STUB for Phase 0 (PHASES.md §0.C repo structure lists this file; content
# is filled in during Phase 1 — "Pub/Sub topics" — per spec §25 build
# sequencing, and consumed from Phase 2 onward by the adapters in
# backend/app/adapters/).
#
# Structure is fixed now so the shape doesn't need reinventing later:
# every inbound Channel (contracts/events.py) gets one topic; every
# SubsystemName routing target (contracts/events.py) gets one topic. Both
# enums are frozen by the CTO — this script's job is to mirror them 1:1,
# never to invent topic names independently.
#
# Idempotent: `gcloud pubsub topics create` is a no-op (with a warning,
# not a failure) if the topic already exists; this script treats that as
# success.
#
# Usage (once Phase 1/2 fills in the TODO lists below):
#   ./infra/pubsub_topics.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

echo "=================================================================="
echo " GharOS — Pub/Sub topics (Phase 1/2 content, Phase 0 skeleton)"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id"

# TODO(Phase 1, E3): one inbound topic per contracts.events.Channel value,
# prefixed with PUBSUB_TOPIC_PREFIX (see .env.example: "gharos-"), e.g.:
#   gharos-inbound-email
#   gharos-inbound-document-upload
#   gharos-inbound-sms-upi-alert
#   gharos-inbound-whatsapp
#   gharos-inbound-portal-notification
#   gharos-inbound-voice-telephony
#   gharos-inbound-voice-household
#   gharos-inbound-scheduled-tick
#   gharos-inbound-manual-intention
INBOUND_TOPICS=(
  # "gharos-inbound-email"
  # "gharos-inbound-document-upload"
  # ...
)

# TODO(Phase 1/2, E3): one routing topic per contracts.events.SubsystemName
# value, for the Intake Router's fan-out, e.g.:
#   gharos-route-consequence-engine
#   gharos-route-fair-allocator
#   gharos-route-intention-action
#   gharos-route-household-ledger
#   gharos-route-simulator
#   gharos-route-council
#   gharos-route-outbound-concierge
ROUTING_TOPICS=(
  # "gharos-route-consequence-engine"
  # ...
)

ALL_TOPICS=("${INBOUND_TOPICS[@]}" "${ROUTING_TOPICS[@]}")

if [[ ${#ALL_TOPICS[@]} -eq 0 ]]; then
  log "No topics defined yet — this is expected in Phase 0."
  log "Phase 1/2 fills in INBOUND_TOPICS and ROUTING_TOPICS above, mirroring"
  log "contracts/events.py Channel and SubsystemName enums 1:1."
  exit 0
fi

for topic in "${ALL_TOPICS[@]}"; do
  if gcloud pubsub topics describe "$topic" --project "$project_id" >/dev/null 2>&1; then
    log "  already exists: $topic"
  else
    log "  creating: $topic"
    gcloud pubsub topics create "$topic" --project "$project_id" --quiet
  fi
done

echo "=================================================================="
log "Pub/Sub topics reconciled for project $project_id."
echo "=================================================================="
