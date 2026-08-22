#!/usr/bin/env bash
# GharOS — infra/budget_alert.sh
#
# PHASES.md §0.C / §6.2.7: "Budget alert configured in Phase 0" (~$25,
# 50%/90% thresholds) "and must stay active." This is a standing cost-
# control requirement, not a one-time nicety — E3 owns it.
#
# Idempotent: checks for an existing GharOS budget by display name before
# creating a new one. Requires a billing account to be linked (setup_gcp.sh
# step 3 does this) — if none is found, this script says so explicitly and
# exits non-zero. It never silently skips the alert.
#
# Usage:
#   ./infra/budget_alert.sh
#   BUDGET_AMOUNT_USD=25 ./infra/budget_alert.sh   # override the default

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

readonly BUDGET_DISPLAY_NAME="GharOS monthly budget"
readonly BUDGET_AMOUNT_USD="${BUDGET_AMOUNT_USD:-25}"

echo "=================================================================="
echo " GharOS — budget alert (\$${BUDGET_AMOUNT_USD}, 50%/90% thresholds)"
echo "=================================================================="

require_gcloud
require_auth

project_id="$(resolve_project_id || true)"
[[ -n "$project_id" ]] || die "No GharOS project found. Run ./infra/setup_gcp.sh first."
log "Project: $project_id"

# --- locate billing account ----------------------------------------------

log "Looking up billing account linked to $project_id..."
billing_account="$(gcloud billing projects describe "$project_id" \
  --format='value(billingAccountName)' 2>/dev/null | sed 's#^billingAccounts/##' || true)"

if [[ -z "$billing_account" ]]; then
  log "No billing account linked to this project yet. Checking for any open billing account..."
  billing_account="$(gcloud billing accounts list \
    --filter='open=true' --format='value(name)' --limit=1 2>/dev/null | sed 's#^billingAccounts/##' || true)"
fi

if [[ -z "$billing_account" ]]; then
  cat >&2 <<EOF

xx No billing account is available for this gcloud identity.

   A budget alert requires a billing account before it can be created.
   This is NOT silently skipped — you must resolve it and re-run:

   1. Create or locate a billing account:
        https://console.cloud.google.com/billing
   2. Link it to the GharOS project:
        gcloud billing projects link $project_id --billing-account=<BILLING_ACCOUNT_ID>
   3. Re-run this script:
        ./infra/budget_alert.sh

EOF
  exit 1
fi

log "Billing account: $billing_account"

# --- check billing budgets API is usable ---------------------------------

if ! gcloud billing budgets list --billing-account="$billing_account" >/dev/null 2>&1; then
  warn "Could not list budgets on billing account $billing_account."
  warn "This usually means the 'billingbudgets.googleapis.com' API needs enabling, or"
  warn "the authenticated account lacks the 'Billing Account Costs Manager' role."
  warn "Enable it with:"
  warn "  gcloud services enable billingbudgets.googleapis.com --project=$project_id"
  exit 1
fi

# --- idempotent create/skip -----------------------------------------------

log "Checking for an existing '$BUDGET_DISPLAY_NAME' budget..."
existing="$(gcloud billing budgets list --billing-account="$billing_account" \
  --filter="displayName='${BUDGET_DISPLAY_NAME}'" --format='value(name)' --limit=1 2>/dev/null || true)"

if [[ -n "$existing" ]]; then
  log "Budget already exists: $existing (skipping creation)"
  log "To change the amount or thresholds, edit it in the console:"
  log "  https://console.cloud.google.com/billing/${billing_account}/budgets"
else
  log "Creating budget '$BUDGET_DISPLAY_NAME' — \$${BUDGET_AMOUNT_USD}, alerts at 50% and 90%..."
  gcloud billing budgets create \
    --billing-account="$billing_account" \
    --display-name="$BUDGET_DISPLAY_NAME" \
    --budget-amount="${BUDGET_AMOUNT_USD}USD" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --filter-projects="projects/$project_id" \
    --quiet
  log "Budget created. Default GCP billing alert emails go to Billing Account Administrators/Users."
fi

echo "=================================================================="
log "Budget alert active for project $project_id (\$${BUDGET_AMOUNT_USD}, 50%/90%)."
log "This must stay active for the life of the project (PHASES.md §6.2.7)."
echo "=================================================================="
