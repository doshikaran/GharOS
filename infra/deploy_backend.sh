#!/usr/bin/env bash
# GharOS — infra/deploy_backend.sh
#
# PHASES.md §0.C:
#   gcloud run deploy gharos-api --source ./backend --region asia-south1 \
#     --min-instances=0 --max-instances=2 --allow-unauthenticated
#
# Source deploy via Cloud Buildpacks — NO Dockerfile. This script enforces
# the "no Docker, source deploy only" discipline at deploy time: it fails
# fast, before touching gcloud, if backend/Procfile or backend/requirements.txt
# is missing (buildpacks need both to build a Python source without a
# Dockerfile) — and it fails fast if a Dockerfile is present anywhere under
# backend/, because that would silently switch Cloud Run onto a Docker
# build path instead of buildpacks.
#
# Cost control (PHASES.md §6.2, non-negotiable, owned by E3):
#   --min-instances=0 is NEVER overridden, even via env var. There is no
#   escape hatch for this in the script on purpose.
#   --max-instances=2 initially.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root
source ./infra/_common.sh

readonly BACKEND_DIR="./backend"
readonly MAX_INSTANCES="${GHAROS_BACKEND_MAX_INSTANCES:-2}"

echo "=================================================================="
echo " GharOS — deploy backend ($GHAROS_API_SERVICE) via source buildpack"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id  Region: $GHAROS_REGION"

# --- fail fast: buildpack discipline --------------------------------------

log "Checking buildpack prerequisites in $BACKEND_DIR..."
require_file "$BACKEND_DIR/Procfile" "backend/Procfile"
require_file "$BACKEND_DIR/requirements.txt" "backend/requirements.txt"

if find "$BACKEND_DIR" -iname "Dockerfile*" 2>/dev/null | grep -q .; then
  die "A Dockerfile was found under $BACKEND_DIR. GharOS uses buildpack source deploys only (PHASES.md §3.1) — remove it before deploying."
fi
log "Procfile, requirements.txt present; no Dockerfile found. OK."

# --- hard cost-control guard ------------------------------------------

if [[ "${GHAROS_BACKEND_MIN_INSTANCES:-0}" != "0" ]]; then
  die "--min-instances must be 0 (PHASES.md §6.2 rule 1, non-negotiable). Refusing to deploy with GHAROS_BACKEND_MIN_INSTANCES=${GHAROS_BACKEND_MIN_INSTANCES}."
fi
log "min-instances=0 confirmed (never overridden). max-instances=$MAX_INSTANCES."

# --- deploy ----------------------------------------------------------------

log "Deploying $GHAROS_API_SERVICE from $BACKEND_DIR (source build, no Dockerfile)..."
gcloud run deploy "$GHAROS_API_SERVICE" \
  --source "$BACKEND_DIR" \
  --project "$project_id" \
  --region "$GHAROS_REGION" \
  --min-instances=0 \
  --max-instances="$MAX_INSTANCES" \
  --allow-unauthenticated \
  --quiet

service_url="$(gcloud run services describe "$GHAROS_API_SERVICE" \
  --project "$project_id" --region "$GHAROS_REGION" --format='value(status.url)')"

echo "=================================================================="
log "Deployed: $GHAROS_API_SERVICE"
log "URL:      $service_url"
log "Verify buildpack (not Docker) build: gcloud run revisions describe <revision> --region=$GHAROS_REGION"
log "Remember: ./infra/teardown.sh after capturing deployment proof (docs/DEPLOYMENT_PROOF.md)."
echo "=================================================================="
