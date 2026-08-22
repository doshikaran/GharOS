#!/usr/bin/env bash
# GharOS — infra/setup_gcp.sh
#
# Idempotent version of PHASES.md §0.C:
#   gcloud auth login
#   gcloud projects create gharos-<suffix> --name="GharOS"
#   gcloud config set project gharos-<suffix>
#   gcloud services enable run.googleapis.com firestore.googleapis.com pubsub.googleapis.com \
#     aiplatform.googleapis.com cloudscheduler.googleapis.com secretmanager.googleapis.com \
#     cloudbuild.googleapis.com
#   gcloud firestore databases create --location=asia-south1
#
# Safe to re-run any number of times: every step checks current state
# before acting. Nothing here creates a second project, re-enables an
# already-enabled API, or fails because a database already exists.
#
# Usage:
#   ./infra/setup_gcp.sh
#   PROJECT_SUFFIX=myteam ./infra/setup_gcp.sh     # pin the project id
#   GHAROS_PROJECT_ID=gharos-existing ./infra/setup_gcp.sh   # reuse exactly this project
#
# Owned by E3 (PHASES.md §1, §4). Do not hardcode a project id literal —
# see infra/_common.sh:resolve_project_id.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

echo "=================================================================="
echo " GharOS — Phase 0.C cloud project setup"
echo "=================================================================="

require_gcloud

# --- step 1: authentication -------------------------------------------

log "Step 1/5 — checking gcloud authentication..."
active_account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
if [[ -z "$active_account" ]]; then
  log "No active gcloud session found. Launching 'gcloud auth login' (interactive; a browser tab will open)."
  gcloud auth login
  active_account="$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null || true)"
  [[ -n "$active_account" ]] || die "Authentication did not complete. Re-run this script after 'gcloud auth login' succeeds."
else
  log "Already authenticated as: $active_account (skipping login)"
fi

# --- step 2: project ----------------------------------------------------

log "Step 2/5 — resolving GharOS project..."
project_id="$(resolve_project_id || true)"

if [[ -n "$project_id" ]]; then
  log "Found existing GharOS project: $project_id (skipping creation)"
else
  project_id="$(generate_project_id)"
  log "No existing GharOS project found. Creating: $project_id"
  gcloud projects create "$project_id" --name="$GHAROS_PROJECT_DISPLAY_NAME" --quiet
  log "Created project: $project_id"
  log "Remember this id — the fastest way to pin it on future runs:"
  log "  export GHAROS_PROJECT_ID=$project_id"
fi

log "Setting active gcloud config project to: $project_id"
gcloud config set project "$project_id" --quiet

# --- step 3: billing (required before services can be enabled) ---------

log "Step 3/5 — checking billing account link..."
billing_enabled="$(gcloud billing projects describe "$project_id" \
  --format='value(billingEnabled)' 2>/dev/null || echo "false")"

if [[ "$billing_enabled" == "True" ]]; then
  log "Billing already linked to $project_id."
else
  billing_account="$(gcloud billing accounts list \
    --filter='open=true' --format='value(name)' --limit=1 2>/dev/null || true)"
  if [[ -z "$billing_account" ]]; then
    warn "No open billing account found on this gcloud identity."
    warn "Cloud Run / Firestore / Vertex AI / Scheduler cannot be enabled without billing."
    warn "Link a billing account manually, e.g.:"
    warn "  gcloud billing accounts list"
    warn "  gcloud billing projects link $project_id --billing-account=<BILLING_ACCOUNT_ID>"
    warn "Then re-run this script."
    exit 1
  fi
  log "Linking billing account $billing_account to $project_id..."
  gcloud billing projects link "$project_id" --billing-account="$billing_account" --quiet
  log "Billing linked."
fi

# --- step 4: enable APIs -------------------------------------------------

log "Step 4/5 — checking required APIs..."
enabled_apis="$(gcloud services list --enabled --format='value(config.name)' --project="$project_id" 2>/dev/null || true)"

apis_to_enable=()
for api in "${GHAROS_REQUIRED_APIS[@]}"; do
  if grep -qx "$api" <<<"$enabled_apis"; then
    log "  already enabled: $api"
  else
    apis_to_enable+=("$api")
  fi
done

if [[ ${#apis_to_enable[@]} -eq 0 ]]; then
  log "All required APIs already enabled."
else
  log "Enabling: ${apis_to_enable[*]}"
  gcloud services enable "${apis_to_enable[@]}" --project="$project_id" --quiet
  log "APIs enabled."
fi

# --- step 5: firestore database -----------------------------------------

log "Step 5/5 — checking Firestore database..."
if gcloud firestore databases describe --database='(default)' --project="$project_id" >/dev/null 2>&1; then
  existing_location="$(gcloud firestore databases describe --database='(default)' \
    --project="$project_id" --format='value(locationId)' 2>/dev/null || true)"
  log "Firestore database already exists in project $project_id (location: ${existing_location:-unknown}) — skipping create."
  if [[ -n "$existing_location" && "$existing_location" != "$GHAROS_REGION" ]]; then
    warn "Existing Firestore location ($existing_location) differs from GHAROS_REGION ($GHAROS_REGION)."
    warn "Firestore location is permanent and cannot be changed after creation — this is informational only."
  fi
else
  log "Creating Firestore database (Native mode) in $GHAROS_REGION..."
  gcloud firestore databases create --location="$GHAROS_REGION" --project="$project_id" --quiet
  log "Firestore database created."
fi

echo "=================================================================="
log "Phase 0.C cloud project setup complete."
log "Project:  $project_id"
log "Region:   $GHAROS_REGION"
log "Next:     ./infra/budget_alert.sh   (budget alert — needs a billing account, checked above)"
log "          ./infra/deploy_backend.sh (after backend/Procfile + requirements.txt exist)"
log "          ./infra/deploy_frontend.sh"
echo "=================================================================="
