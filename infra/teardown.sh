#!/usr/bin/env bash
# GharOS — infra/teardown.sh
#
# PHASES.md §6.2.6: "infra/teardown.sh scales to zero; run after every
# proof capture." This is a standing cost-control rule, not a one-off
# script — run this every time after grabbing screenshots/logs for
# docs/DEPLOYMENT_PROOF.md.
#
# Scales both Cloud Run services (gharos-api, gharos-web) to
# min-instances=0 / max-instances=0. This does not delete the services or
# their revision history — proof (Cloud Run revision detail, source build
# logs) stays intact for docs/DEPLOYMENT_PROOF.md; it just guarantees zero
# running instances and therefore zero compute spend until the next deploy.
#
# Idempotent: safe to run when a service doesn't exist yet (skipped with a
# note) or is already scaled to zero (no-op update).
#
# Usage:
#   ./infra/teardown.sh

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

echo "=================================================================="
echo " GharOS — teardown (scale Cloud Run services to zero)"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Nothing to tear down."
log "Project: $project_id  Region: $GHAROS_REGION"

scale_to_zero() {
  local service="$1"
  if ! gcloud run services describe "$service" \
      --project "$project_id" --region "$GHAROS_REGION" >/dev/null 2>&1; then
    log "  $service: not deployed — nothing to scale down."
    return 0
  fi

  log "  $service: scaling to min-instances=0, max-instances=0..."
  gcloud run services update "$service" \
    --project "$project_id" \
    --region "$GHAROS_REGION" \
    --min-instances=0 \
    --max-instances=0 \
    --quiet
  log "  $service: scaled to zero."
}

log "Scaling GharOS Cloud Run services to zero..."
scale_to_zero "$GHAROS_API_SERVICE"
scale_to_zero "$GHAROS_WEB_SERVICE"

echo "=================================================================="
log "Teardown complete. Both services (where deployed) are at zero instances."
log "Revisions and logs are preserved for docs/DEPLOYMENT_PROOF.md."
log "To resume serving, re-run ./infra/deploy_backend.sh / ./infra/deploy_frontend.sh"
log "(which restore max-instances=2, min-instances stays 0 — cost control is never overridden)."
echo "=================================================================="
