#!/usr/bin/env bash
# GharOS — infra/deploy_frontend.sh
#
# Mirrors deploy_backend.sh for the Next.js service (PHASES.md §0.C /
# §3.1): source deploy via Cloud Buildpacks, NO Dockerfile. Buildpacks
# build a standard Next.js `package.json` with `build` and a `start` that
# binds `$PORT` (Next.js's `next start` does this automatically).
#
# Cost control (PHASES.md §6.2, non-negotiable, owned by E3):
#   --min-instances=0 is NEVER overridden.
#   --max-instances=2 initially.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."   # repo root
source ./infra/_common.sh

readonly FRONTEND_DIR="./frontend"
readonly MAX_INSTANCES="${GHAROS_FRONTEND_MAX_INSTANCES:-2}"

echo "=================================================================="
echo " GharOS — deploy frontend ($GHAROS_WEB_SERVICE) via source buildpack"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id  Region: $GHAROS_REGION"

# --- fail fast: buildpack discipline --------------------------------------

log "Checking buildpack prerequisites in $FRONTEND_DIR..."
require_file "$FRONTEND_DIR/package.json" "frontend/package.json"

if ! grep -q '"build"' "$FRONTEND_DIR/package.json"; then
  die "frontend/package.json has no 'build' script — required for a buildpack source deploy."
fi
if ! grep -q '"start"' "$FRONTEND_DIR/package.json"; then
  die "frontend/package.json has no 'start' script binding \$PORT — required for a buildpack source deploy."
fi

if find "$FRONTEND_DIR" -iname "Dockerfile*" -not -path "*/node_modules/*" 2>/dev/null | grep -q .; then
  die "A Dockerfile was found under $FRONTEND_DIR. GharOS uses buildpack source deploys only (PHASES.md §3.1) — remove it before deploying."
fi
log "package.json build/start scripts present; no Dockerfile found. OK."

# --- hard cost-control guard ------------------------------------------

if [[ "${GHAROS_FRONTEND_MIN_INSTANCES:-0}" != "0" ]]; then
  die "--min-instances must be 0 (PHASES.md §6.2 rule 1, non-negotiable). Refusing to deploy with GHAROS_FRONTEND_MIN_INSTANCES=${GHAROS_FRONTEND_MIN_INSTANCES}."
fi
log "min-instances=0 confirmed (never overridden). max-instances=$MAX_INSTANCES."

# --- deploy ----------------------------------------------------------------

log "Deploying $GHAROS_WEB_SERVICE from $FRONTEND_DIR (source build, no Dockerfile)..."
gcloud run deploy "$GHAROS_WEB_SERVICE" \
  --source "$FRONTEND_DIR" \
  --project "$project_id" \
  --region "$GHAROS_REGION" \
  --min-instances=0 \
  --max-instances="$MAX_INSTANCES" \
  --allow-unauthenticated \
  --quiet

service_url="$(gcloud run services describe "$GHAROS_WEB_SERVICE" \
  --project "$project_id" --region "$GHAROS_REGION" --format='value(status.url)')"

echo "=================================================================="
log "Deployed: $GHAROS_WEB_SERVICE"
log "URL:      $service_url"
log "Remember: ./infra/teardown.sh after capturing deployment proof (docs/DEPLOYMENT_PROOF.md)."
echo "=================================================================="
