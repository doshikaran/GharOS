#!/usr/bin/env bash
# GharOS — infra/pubsub_topics.sh
#
# PHASES.md Phase 2 work item ("Pub/Sub topics + push subscription to the
# API"). Creates the two topics the Phase 2 stack proof needs:
#
#   gharos-events     — generic inbound-events topic. A full one-topic-per
#                        `contracts.events.Channel` split (email, document
#                        upload, SMS/UPI, WhatsApp, ...) is an ingestion-
#                        adapter design decision that belongs to Phase 3,
#                        when those adapters actually exist to publish onto
#                        them (PHASES.md Phase 3, "Contributing — ... the
#                        registry as a strategy pattern, adapters"). Standing
#                        up nine empty topics with no publisher and no
#                        subscriber yet would be exactly the kind of
#                        accidental-fan-out surface area the charter's cost
#                        section warns against — this topic exists now only
#                        to prove the Pub/Sub round trip end to end.
#   gharos-heartbeat   — Cloud Scheduler's heartbeat tick
#                        (`infra/scheduler_jobs.sh`), delivered to the
#                        deployed API via a push subscription configured by
#                        this script. Received at `POST /events/heartbeat`
#                        (`backend/app/api/pubsub_receiver.py`'s
#                        `receive_heartbeat` route — this script's push
#                        endpoint path is read from that module, not
#                        guessed).
#
# Also reconciles the push subscription's OIDC identity: Pub/Sub push
# subscriptions authenticate to their endpoint via a signed identity token
# minted for a service account (`--push-auth-service-account`). This script
# creates a dedicated `gharos-pubsub-invoker` service account (never reuses
# the default compute service account — least privilege, spec §23), grants
# it `roles/run.invoker` on `gharos-api`, and wires the deployed service's
# `PUBSUB_PUSH_SERVICE_ACCOUNT_EMAIL` / `PUBSUB_PUSH_AUDIENCE` env vars
# (`backend/app/settings.py`) so `verify_push_request` actually checks the
# token instead of skipping verification.
#
# Two realistic deploy states, handled explicitly rather than assumed:
#   (a) gharos-api already deployed — this script looks up its live URL via
#       `gcloud run services describe` and creates/updates the push
#       subscription immediately, end to end.
#   (b) gharos-api not deployed yet — this script creates the topics and
#       the service account (both deploy-independent) and prints the exact
#       next steps; it does not fail, because "topics exist, push
#       subscription pending deploy" is a valid, expected intermediate
#       state early in Phase 2, not an error.
#
# Idempotent throughout: every gcloud mutation is preceded by a `describe`
# check-before-create/update, matching infra/setup_gcp.sh's convention.
#
# Usage:
#   ./infra/pubsub_topics.sh
#   # ... after ./infra/deploy_backend.sh has run at least once ...
#   ./infra/pubsub_topics.sh   # re-run to wire the push subscription

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

echo "=================================================================="
echo " GharOS — Pub/Sub topics + heartbeat push subscription"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id  Region: $GHAROS_REGION"

readonly EVENTS_TOPIC="gharos-events"
readonly HEARTBEAT_TOPIC="gharos-heartbeat"
readonly TOPICS=("$EVENTS_TOPIC" "$HEARTBEAT_TOPIC")

readonly HEARTBEAT_PUSH_SUBSCRIPTION="gharos-heartbeat-push"
# Must match the route `app.api.pubsub_receiver.router` actually registers
# (`@router.post("/heartbeat")` under `prefix="/events"`) — read from the
# module, not guessed, per this script's own header.
readonly HEARTBEAT_PUSH_PATH="/events/heartbeat"
readonly PUSH_INVOKER_SA_NAME="gharos-pubsub-invoker"
readonly PUSH_INVOKER_SA_EMAIL="${PUSH_INVOKER_SA_NAME}@${project_id}.iam.gserviceaccount.com"

# --- step 1: topics ------------------------------------------------------

log "Step 1/3 — reconciling Pub/Sub topics..."
for topic in "${TOPICS[@]}"; do
  if gcloud pubsub topics describe "$topic" --project "$project_id" >/dev/null 2>&1; then
    log "  already exists: $topic"
  else
    log "  creating: $topic"
    gcloud pubsub topics create "$topic" --project "$project_id" --quiet
  fi
done

# --- step 2: dedicated push-auth service account --------------------------

log "Step 2/3 — reconciling the push-auth service account..."
if gcloud iam service-accounts describe "$PUSH_INVOKER_SA_EMAIL" --project "$project_id" >/dev/null 2>&1; then
  log "  already exists: $PUSH_INVOKER_SA_EMAIL"
else
  log "  creating: $PUSH_INVOKER_SA_EMAIL"
  gcloud iam service-accounts create "$PUSH_INVOKER_SA_NAME" \
    --project "$project_id" \
    --display-name="GharOS Pub/Sub push invoker (OIDC identity for push subscriptions -> gharos-api)" \
    --quiet
fi

# --- step 3: push subscription (needs a deployed service URL) -------------

log "Step 3/3 — checking whether $GHAROS_API_SERVICE is deployed..."
service_url=""
if service_url="$(gcloud run services describe "$GHAROS_API_SERVICE" \
    --project "$project_id" --region "$GHAROS_REGION" \
    --format='value(status.url)' 2>/dev/null)" && [[ -n "$service_url" ]]; then

  log "  $GHAROS_API_SERVICE is deployed at: $service_url"
  push_endpoint="${service_url}${HEARTBEAT_PUSH_PATH}"

  log "  granting roles/run.invoker on $GHAROS_API_SERVICE to $PUSH_INVOKER_SA_EMAIL..."
  gcloud run services add-iam-policy-binding "$GHAROS_API_SERVICE" \
    --project "$project_id" --region "$GHAROS_REGION" \
    --member="serviceAccount:$PUSH_INVOKER_SA_EMAIL" \
    --role="roles/run.invoker" \
    --quiet >/dev/null

  if gcloud pubsub subscriptions describe "$HEARTBEAT_PUSH_SUBSCRIPTION" --project "$project_id" >/dev/null 2>&1; then
    log "  updating push subscription: $HEARTBEAT_PUSH_SUBSCRIPTION -> $push_endpoint"
    gcloud pubsub subscriptions update "$HEARTBEAT_PUSH_SUBSCRIPTION" \
      --project "$project_id" \
      --push-endpoint="$push_endpoint" \
      --push-auth-service-account="$PUSH_INVOKER_SA_EMAIL" \
      --push-auth-token-audience="$push_endpoint" \
      --quiet
  else
    log "  creating push subscription: $HEARTBEAT_PUSH_SUBSCRIPTION -> $push_endpoint"
    gcloud pubsub subscriptions create "$HEARTBEAT_PUSH_SUBSCRIPTION" \
      --project "$project_id" \
      --topic="$HEARTBEAT_TOPIC" \
      --push-endpoint="$push_endpoint" \
      --push-auth-service-account="$PUSH_INVOKER_SA_EMAIL" \
      --push-auth-token-audience="$push_endpoint" \
      --quiet
  fi

  log "  wiring $GHAROS_API_SERVICE's push-verification env vars (PUBSUB_PUSH_SERVICE_ACCOUNT_EMAIL, PUBSUB_PUSH_AUDIENCE)..."
  gcloud run services update "$GHAROS_API_SERVICE" \
    --project "$project_id" --region "$GHAROS_REGION" \
    --update-env-vars="PUBSUB_PUSH_SERVICE_ACCOUNT_EMAIL=${PUSH_INVOKER_SA_EMAIL},PUBSUB_PUSH_AUDIENCE=${push_endpoint}" \
    --quiet >/dev/null

  log "  push subscription wired; heartbeat verification is now enforced (not skipped)."
else
  warn "  $GHAROS_API_SERVICE is not deployed yet in project $project_id / region $GHAROS_REGION."
  warn "  Topics and the push-auth service account are ready; the push subscription itself needs a live service URL."
  log "  Next steps:"
  log "    1. ./infra/deploy_backend.sh"
  log "    2. ./infra/pubsub_topics.sh   (re-run this script — it will find the URL, grant roles/run.invoker,"
  log "                                   create/update the push subscription, and set the receiver's env vars)"
fi

echo "=================================================================="
log "Pub/Sub topics reconciled for project $project_id: ${TOPICS[*]}"
if [[ -n "$service_url" ]]; then
  log "Heartbeat push subscription: $HEARTBEAT_PUSH_SUBSCRIPTION -> ${service_url}${HEARTBEAT_PUSH_PATH}"
else
  log "Heartbeat push subscription: not yet created (gharos-api not deployed) — see next steps above."
fi
echo "=================================================================="
