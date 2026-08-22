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
# Currency-aware: `gcloud billing budgets create --budget-amount` requires
# an amount denominated in the billing account's OWN currency — passing a
# mismatched currency code (e.g. "25USD" on an INR-denominated account)
# fails with an opaque INVALID_ARGUMENT and no mention of currency at all.
# This script reads the billing account's real `currencyCode` first and
# never assumes USD.
#
# Usage:
#   ./infra/budget_alert.sh
#   BUDGET_AMOUNT_USD=25 ./infra/budget_alert.sh    # only used if account currency is USD
#   BUDGET_AMOUNT_NATIVE=2000 ./infra/budget_alert.sh   # explicit amount in the account's own currency, any currency

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"
source ./_common.sh

readonly BUDGET_DISPLAY_NAME="GharOS monthly budget"
# Rough USD-equivalent defaults for non-USD accounts, so the ~$25 guardrail
# from PHASES.md §6.2.7 stays meaningful in the account's native currency
# without requiring the operator to do currency math. This is intentionally
# a short, explicit table, not a live FX lookup (a live conversion API is
# both unnecessary precision for a budget *guardrail* and one more external
# dependency this script would need to fail gracefully around) — if your
# account's currency isn't listed, set BUDGET_AMOUNT_NATIVE explicitly.
default_native_amount_for_currency() {
  case "$1" in
    USD) echo "25" ;;
    INR) echo "2000" ;;
    EUR) echo "23" ;;
    GBP) echo "20" ;;
    *)   echo "" ;;
  esac
}

echo "=================================================================="
echo " GharOS — budget alert (~\$25 guardrail, 50%/90% thresholds)"
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

# --- determine the account's currency, and the amount to use in it -------

currency_code="$(gcloud billing accounts describe "$billing_account" \
  --format='value(currencyCode)' 2>/dev/null || true)"
[[ -n "$currency_code" ]] || die "Could not read the billing account's currencyCode from 'gcloud billing accounts describe $billing_account'."
log "Billing account currency: $currency_code"

if [[ -n "${BUDGET_AMOUNT_NATIVE:-}" ]]; then
  budget_amount="$BUDGET_AMOUNT_NATIVE"
  log "Using explicit BUDGET_AMOUNT_NATIVE=$budget_amount $currency_code"
elif [[ "$currency_code" == "USD" ]]; then
  budget_amount="${BUDGET_AMOUNT_USD:-25}"
else
  budget_amount="$(default_native_amount_for_currency "$currency_code")"
  if [[ -z "$budget_amount" ]]; then
    die "No default guardrail amount known for currency '$currency_code'. Set BUDGET_AMOUNT_NATIVE=<amount> and re-run (e.g. BUDGET_AMOUNT_NATIVE=2000 for roughly \$25 in a ~80/USD currency)."
  fi
  log "Account currency ($currency_code) isn't USD — using ~\$25-equivalent default: $budget_amount $currency_code. Override with BUDGET_AMOUNT_NATIVE if you want a different amount."
fi

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
  log "Creating budget '$BUDGET_DISPLAY_NAME' — ${budget_amount} ${currency_code}, alerts at 50% and 90%..."
  project_number="$(gcloud projects describe "$project_id" --format='value(projectNumber)')"
  gcloud billing budgets create \
    --billing-account="$billing_account" \
    --display-name="$BUDGET_DISPLAY_NAME" \
    --budget-amount="${budget_amount}${currency_code}" \
    --threshold-rule=percent=0.5 \
    --threshold-rule=percent=0.9 \
    --filter-projects="projects/${project_number}" \
    --quiet
  log "Budget created. Default GCP billing alert emails go to Billing Account Administrators/Users."
fi

echo "=================================================================="
log "Budget alert active for project $project_id (${budget_amount} ${currency_code}, 50%/90%)."
log "This must stay active for the life of the project (PHASES.md §6.2.7)."
echo "=================================================================="
