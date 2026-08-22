#!/usr/bin/env bash
# GharOS — infra/_common.sh
#
# Shared helpers sourced by every script in infra/. Not standalone —
# `source`d, never executed directly. Owned by E3 (PHASES.md §1: E3 owns
# `infra/`).
#
# Centralises: region/service naming, colored echo helpers, the "which
# GharOS project are we pointed at" resolution logic (used by setup_gcp.sh,
# deploy_backend.sh, deploy_frontend.sh, teardown.sh, budget_alert.sh,
# pubsub_topics.sh, scheduler_jobs.sh so they all agree on one project
# without a hardcoded literal anywhere — PHASES.md §0.C).

set -euo pipefail

# --- constants -------------------------------------------------------------

readonly GHAROS_REGION="${GHAROS_REGION:-asia-south1}"
readonly GHAROS_PROJECT_DISPLAY_NAME="GharOS"
readonly GHAROS_API_SERVICE="gharos-api"
readonly GHAROS_WEB_SERVICE="gharos-web"
readonly GHAROS_REQUIRED_APIS=(
  run.googleapis.com
  firestore.googleapis.com
  pubsub.googleapis.com
  aiplatform.googleapis.com
  cloudscheduler.googleapis.com
  secretmanager.googleapis.com
  cloudbuild.googleapis.com
)

# --- output helpers ----------------------------------------------------

log()  { echo ">> $*"; }
warn() { echo "!! $*" >&2; }
die()  { echo "xx $*" >&2; exit 1; }

require_gcloud() {
  command -v gcloud >/dev/null 2>&1 || die \
    "gcloud CLI not found on PATH. Install: https://cloud.google.com/sdk/docs/install"
}

require_auth() {
  local active
  active="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
  if [[ -z "$active" ]]; then
    die "No active gcloud auth session. Run 'gcloud auth login' first, then re-run this script."
  fi
  log "Authenticated as: $active"
}

# Resolve the GharOS project id without a hardcoded literal (PHASES.md
# §0.C: "use a PROJECT_SUFFIX env var or generate one ... rather than a
# hardcoded literal"). Resolution order:
#   1. GHAROS_PROJECT_ID env var, if set — explicit override, always wins.
#   2. PROJECT_SUFFIX env var, if set — used as gharos-<suffix>.
#   3. The gcloud CLI's current active project, if it looks like a GharOS
#      project (id starts with "gharos-") and actually exists.
#   4. Any existing project named "GharOS" (survives across shells/days —
#      this is what makes setup_gcp.sh idempotent without a local state
#      file, which would otherwise have to live outside infra/'s ownership
#      boundary).
#   5. Nothing found: caller decides whether to generate a new one.
resolve_project_id() {
  if [[ -n "${GHAROS_PROJECT_ID:-}" ]]; then
    echo "$GHAROS_PROJECT_ID"
    return 0
  fi

  if [[ -n "${PROJECT_SUFFIX:-}" ]]; then
    echo "gharos-${PROJECT_SUFFIX}"
    return 0
  fi

  local current
  current="$(gcloud config get-value project 2>/dev/null || true)"
  if [[ "$current" == gharos-* ]] && gcloud projects describe "$current" >/dev/null 2>&1; then
    echo "$current"
    return 0
  fi

  local existing
  existing="$(gcloud projects list \
    --filter="name=${GHAROS_PROJECT_DISPLAY_NAME}" \
    --format='value(projectId)' \
    --sort-by='projectId' \
    --limit=1 2>/dev/null || true)"
  if [[ -n "$existing" ]]; then
    echo "$existing"
    return 0
  fi

  echo ""
  return 1
}

# Generate a fresh, valid GCP project id: gharos-<yyyymmdd>-<4 hex chars>.
# GCP project ids must be 6-30 chars, lowercase letters/digits/hyphens,
# start with a lowercase letter — this format satisfies all three with
# room to spare.
generate_project_id() {
  local date_part rand_part
  date_part="$(date +%Y%m%d)"
  rand_part="$(printf '%04x' $((RANDOM % 65536)))"
  echo "gharos-${date_part}-${rand_part}"
}

# Fail fast if a required file is missing at a service root — this is the
# structural enforcement of "no Docker, source deploy only" at deploy time
# (charter: E3 owns this discipline).
require_file() {
  local path="$1" what="$2"
  [[ -f "$path" ]] || die "$what not found at: $path (required for a buildpack source deploy)."
}

# Every Cloud Run service is reachable at TWO distinct, independently
# resolving URLs — a `<service>-<hash>.<region>.run.app` alias (what
# `gcloud run services describe --format='value(status.url)'` reports) and
# a `<service>-<project-number>.<region>.run.app` canonical form (what
# `gcloud run deploy`'s own success message prints). Discovered live in
# Phase 2: a browser can legitimately arrive at a frontend via either form,
# so anything that needs "the frontend's real origin" (CORS_ALLOWED_ORIGINS
# in deploy_backend.sh) must allow both, not just whichever one `status.url`
# happens to report — an allowlist of only one is a real, silent breakage
# waiting for whoever loads the app from the other URL.
#
# Echoes a comma-separated list of both URLs for $1 (a deployed service
# name), or nothing (empty string, exit 1) if the service isn't deployed.
service_urls() {
  local service="$1" project_id="$2"
  local alias_url project_number canonical_url
  alias_url="$(gcloud run services describe "$service" \
    --project "$project_id" --region "$GHAROS_REGION" --format='value(status.url)' 2>/dev/null || true)"
  [[ -n "$alias_url" ]] || { echo ""; return 1; }

  project_number="$(gcloud projects describe "$project_id" --format='value(projectNumber)' 2>/dev/null || true)"
  if [[ -n "$project_number" ]]; then
    canonical_url="https://${service}-${project_number}.${GHAROS_REGION}.run.app"
    echo "${alias_url},${canonical_url}"
  else
    echo "$alias_url"
  fi
  return 0
}
