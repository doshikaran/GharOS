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

# --- runtime env vars -------------------------------------------------
#
# There is no backend/.env inside the deployed container (`.env` is
# git-ignored and never shipped — gharos-standards rule 8: "no secrets in
# code"), so every `app.settings.Settings` field the deployed process
# actually needs at startup must arrive as a real Cloud Run env var instead.
# Names must match `app.settings.Settings`'s field names exactly
# (pydantic-settings uppercases the field name; `.env.example` documents
# the same mapping) — verified against backend/app/settings.py, not
# guessed.
#
# GCP_PROJECT_ID is the critical one: without it, `create_firestore_client`
# (backend/app/persistence/firestore_client.py) has no
# FIRESTORE_EMULATOR_HOST to fall back to in a real deployment and raises
# rather than guessing a project id — so an unset GCP_PROJECT_ID here is a
# deploy-time misconfiguration, not a soft default. GCP_REGION and
# VERTEX_AI_LOCATION are passed explicitly too, rather than relying on
# Settings' hardcoded default matching $GHAROS_REGION by coincidence.
#
# Deliberately NOT set here: FIRESTORE_EMULATOR_HOST, PUBSUB_EMULATOR_HOST
# (must stay unset in a real deployment so the SDKs talk to the real
# services, never an emulator) and PUBSUB_PUSH_SERVICE_ACCOUNT_EMAIL /
# PUBSUB_PUSH_AUDIENCE (wired post-deploy by ./infra/pubsub_topics.sh, once
# this deploy has produced the service URL that audience value needs).
#
# CORS_ALLOWED_ORIGINS: if gharos-web is already deployed, allow BOTH of
# its real URL forms (see _common.sh:service_urls — every Cloud Run
# service resolves at two distinct URLs, and a browser can legitimately
# land on either one). Never a wildcard — Settings.cors_allowed_origins.
# If not deployed yet, this stays empty and app.main installs no
# CORSMiddleware at all — re-run this script (or just
# ./infra/deploy_frontend.sh, which looks gharos-api's URL up the same way)
# after gharos-web exists to wire it.
web_urls="$(service_urls "$GHAROS_WEB_SERVICE" "$project_id" || true)"
if [[ -n "$web_urls" ]]; then
  log "Found deployed gharos-web at: $web_urls — allowing both via CORS_ALLOWED_ORIGINS."
else
  log "gharos-web not deployed yet — CORS_ALLOWED_ORIGINS left empty (no CORSMiddleware installed). Re-run after deploying it."
fi
# --- OAuth ingestion-connector env vars (Phase 14.5, ADR-022) -----------
#
# `app.api.oauth_router` / the Gmail + Outlook connectors read these from
# `app.settings.Settings`. They are OPTIONAL — with none set, the OAuth
# routes return a clean 503 ("not configured") and the rest of the service
# runs normally (verified: `get_oauth_client_for` raises 503, it does not
# crash startup). Set them for a deploy that needs the live Connections
# onboarding surface.
#
# HARD RULE, gharos-standards rule 8: the two *client secrets* are NEVER
# passed here as literal values. `GOOGLE_OAUTH_CLIENT_SECRET_REF` /
# `MICROSOFT_OAUTH_CLIENT_SECRET_REF` carry a Secret Manager secret id (or
# full resource name) — a *pointer*, not the secret. `oauth_router`
# resolves it through `SecretManagerAdapter` at request time. This script
# reads every one of these from the operator's shell environment and
# refuses (below) to forward a secret-ref value that looks like a raw
# secret rather than a Secret Manager id.
#
# OAUTH_REDIRECT_BASE_URL must be the public base of THIS service
# (gharos-api) so the provider callback lands back here — it defaults to
# gharos-api's own looked-up URL when the operator doesn't pin it, exactly
# like CORS/api-base-url lookups elsewhere in infra/. FRONTEND_CONNECTIONS_URL
# is where the callback 302s the browser afterwards — defaults to
# `<gharos-web>/connections` when gharos-web is deployed.
oauth_google_id="${GOOGLE_OAUTH_CLIENT_ID:-}"
oauth_google_secret_ref="${GOOGLE_OAUTH_CLIENT_SECRET_REF:-}"
oauth_ms_id="${MICROSOFT_OAUTH_CLIENT_ID:-}"
oauth_ms_secret_ref="${MICROSOFT_OAUTH_CLIENT_SECRET_REF:-}"
oauth_ms_tenant="${MICROSOFT_OAUTH_TENANT:-}"
oauth_redirect_base="${OAUTH_REDIRECT_BASE_URL:-}"
frontend_connections_url="${FRONTEND_CONNECTIONS_URL:-}"

reject_if_looks_like_raw_secret() {
  # A Secret Manager id is a short slug (letters, digits, _ and -) or a
  # `projects/.../secrets/.../versions/...` resource name. A raw Google
  # client secret is ~35 chars starting `GOCSPX-`; an Azure secret value
  # is long and contains characters a secret id never does (`~`, `.`, `/`
  # mid-string outside the resource-name form). Fail closed on the
  # obvious raw-secret shapes rather than silently baking a secret into a
  # plaintext Cloud Run env var.
  local name="$1" value="$2"
  [[ -z "$value" ]] && return 0
  if [[ "$value" == GOCSPX-* ]]; then
    die "$name looks like a raw Google client secret (GOCSPX-...). Put the secret in Secret Manager and pass its id here, not the secret itself (gharos-standards rule 8)."
  fi
  if [[ "$value" == projects/*/secrets/* ]]; then
    return 0  # a full Secret Manager resource name — fine
  fi
  if [[ ! "$value" =~ ^[A-Za-z0-9_-]+$ ]]; then
    die "$name='$value' is neither a bare Secret Manager id ([A-Za-z0-9_-]) nor a projects/*/secrets/* resource name — refusing in case it is a raw secret (gharos-standards rule 8)."
  fi
}
reject_if_looks_like_raw_secret "GOOGLE_OAUTH_CLIENT_SECRET_REF" "$oauth_google_secret_ref"
reject_if_looks_like_raw_secret "MICROSOFT_OAUTH_CLIENT_SECRET_REF" "$oauth_ms_secret_ref"

if [[ -z "$oauth_redirect_base" ]]; then
  api_alias_url="$(gcloud run services describe "$GHAROS_API_SERVICE" \
    --project "$project_id" --region "$GHAROS_REGION" --format='value(status.url)' 2>/dev/null || true)"
  if [[ -n "$api_alias_url" ]]; then
    oauth_redirect_base="$api_alias_url"
    log "OAUTH_REDIRECT_BASE_URL not set — defaulting to gharos-api's live URL: $oauth_redirect_base"
    log "  (the provider app registration's redirect URI must be ${oauth_redirect_base}/oauth/{google,microsoft}/callback)"
  else
    log "OAUTH_REDIRECT_BASE_URL not set and gharos-api has no URL yet — leaving unset (OAuth routes 503 until a re-run wires it)."
  fi
fi
if [[ -z "$frontend_connections_url" && -n "$web_urls" ]]; then
  frontend_connections_url="${web_urls%%,*}/connections"
  log "FRONTEND_CONNECTIONS_URL not set — defaulting to <gharos-web>/connections: $frontend_connections_url"
fi

# --- assemble the env-var argument -------------------------------------
#
# `--set-env-vars` normally splits on `,` between KEY=VALUE pairs — but
# CORS_ALLOWED_ORIGINS's own value legitimately contains a `,` (multiple
# origins). gcloud's fix for exactly this is the `^DELIM^` prefix syntax:
# switch the pair-separator to `;` for this whole argument, which leaves
# `,` free to appear inside any individual value. Using a bare `,`-joined
# string here would silently corrupt the parse (a value's internal comma
# gets read as "start of the next KEY=VALUE pair", producing a bogus pair
# with no `=` and a wrong value for CORS_ALLOWED_ORIGINS) rather than
# raising an obvious error — caught by inspecting the deployed env vars
# after the first attempt, not from a `gcloud` error message.
#
# ENV: `production` by default; set GHAROS_ENV=demo for a demo-hardening
# deploy — that is the single explicit switch that puts the deterministic
# demo path in front of the flaky live external calls (voice TTS today;
# see backend/app/voice/tts_client.py:create_tts_client and
# docs/DEPLOYMENT_PROOF.md "Demo-mode determinism"). The real path stays
# the default; nothing about `production` behaviour changes.
deploy_env="${GHAROS_ENV:-production}"
case "$deploy_env" in
  production | demo | staging) : ;;
  *) die "GHAROS_ENV must be one of: production, demo, staging (got: $deploy_env)" ;;
esac
log "ENV=$deploy_env"

env_pairs=(
  "GCP_PROJECT_ID=${project_id}"
  "GCP_REGION=${GHAROS_REGION}"
  "VERTEX_AI_LOCATION=${GHAROS_REGION}"
  "ENV=${deploy_env}"
  "CORS_ALLOWED_ORIGINS=${web_urls}"
)
# Only forward OAuth vars that actually have a value — an empty
# `OAUTH_REDIRECT_BASE_URL=` would override Settings' own localhost
# default with an empty string, which is worse than leaving it unset.
[[ -n "$oauth_google_id" ]]        && env_pairs+=("GOOGLE_OAUTH_CLIENT_ID=${oauth_google_id}")
[[ -n "$oauth_google_secret_ref" ]] && env_pairs+=("GOOGLE_OAUTH_CLIENT_SECRET_REF=${oauth_google_secret_ref}")
[[ -n "$oauth_ms_id" ]]           && env_pairs+=("MICROSOFT_OAUTH_CLIENT_ID=${oauth_ms_id}")
[[ -n "$oauth_ms_secret_ref" ]]    && env_pairs+=("MICROSOFT_OAUTH_CLIENT_SECRET_REF=${oauth_ms_secret_ref}")
[[ -n "$oauth_ms_tenant" ]]       && env_pairs+=("MICROSOFT_OAUTH_TENANT=${oauth_ms_tenant}")
[[ -n "$oauth_redirect_base" ]]   && env_pairs+=("OAUTH_REDIRECT_BASE_URL=${oauth_redirect_base}")
[[ -n "$frontend_connections_url" ]] && env_pairs+=("FRONTEND_CONNECTIONS_URL=${frontend_connections_url}")

# Guard: none of the assembled values may contain the `;` pair-separator.
for pair in "${env_pairs[@]}"; do
  case "$pair" in
    *";"*) die "env var pair '$pair' contains ';', which is the --set-env-vars delimiter — refusing to deploy a corrupted env." ;;
  esac
done

oauth_keys_set=0
for pair in "${env_pairs[@]}"; do [[ "$pair" == *OAUTH* ]] && oauth_keys_set=$((oauth_keys_set + 1)); done
if [[ "$oauth_keys_set" -eq 0 ]]; then
  log "No OAuth connector env vars set — the /oauth/* routes will return 503 ('not configured'). This is fine for a deploy that doesn't demo the Connections page."
else
  log "OAuth connector env vars set: $oauth_keys_set (secrets by Secret Manager ref only — no literal secret in this deploy)."
fi

IFS=';'
readonly BACKEND_ENV_VARS="^;^${env_pairs[*]}"
unset IFS

# --- stage a self-contained source tree for the buildpack upload ----------
#
# `gcloud run deploy --source` uploads exactly one directory. `contracts/`
# lives at the repo root as a SIBLING of `backend/` (PHASES.md §0.1 — a
# plain, dependency-free, shared package with no pyproject.toml of its
# own), and `backend/app/__init__.py` finds it locally via a `sys.path`
# insert of `Path(__file__).resolve().parents[2]` (two levels above
# `backend/app/`, i.e. the repo root). That trick only works if `contracts/`
# actually exists on disk at that relative position — which it does not
# inside a `--source ./backend` upload, since only `backend/`'s own
# contents are ever uploaded. Deploying `--source ./backend` directly
# therefore builds and starts, but crashes at import time in the deployed
# container with `ModuleNotFoundError: No module named 'contracts'`
# (discovered running this exact deploy in Phase 2 — see
# docs/adr/007-deploy-time-contracts-staging.md for the full decision).
#
# Fix: stage a temporary directory that MIRRORS the real repo layout
# (staging/backend/ + staging/contracts/, same relative depth as the real
# repo root), then deploy `--source` pointing at `staging/backend` — so
# `parents[2]` from the staged `app/__init__.py` resolves to `staging/`,
# which really does contain a `contracts/` sibling, copied fresh from the
# real one on every deploy (never edited in place, always a clean copy of
# whatever `contracts/` currently is — there is exactly one source of
# truth for `contracts/`, this just makes a disposable copy of it reachable
# to the upload).
readonly STAGING_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/gharos-deploy-backend.XXXXXX")"
cleanup_staging() { rm -rf "$STAGING_ROOT"; }
trap cleanup_staging EXIT

log "Staging a self-contained source tree (backend/ + contracts/, nested — ADR-007) in $STAGING_ROOT ..."
mkdir -p "$STAGING_ROOT/backend"
# Exclude local, non-source state that has no business in a build upload:
# venvs, caches, and emulator state (already gitignored, but this script
# must not depend on git status — it copies whatever's on disk).
rsync -a \
  --exclude='.venv/' \
  --exclude='__pycache__/' \
  --exclude='.mypy_cache/' \
  --exclude='.ruff_cache/' \
  --exclude='.pytest_cache/' \
  --exclude='.emulator-pids/' \
  --exclude='.emulator-logs/' \
  --exclude='.env' \
  "$BACKEND_DIR/" "$STAGING_ROOT/backend/"
# `contracts/` goes INSIDE the uploaded directory (backend/contracts/), not
# alongside it — `gcloud run deploy --source` uploads only the exact
# directory named by --source; anything outside it, including a sibling,
# never reaches the build at all. backend/app/__init__.py finds it here via
# an upward search, not a hardcoded depth (see that file's docstring).
rsync -a \
  --exclude='__pycache__/' \
  ./contracts/ "$STAGING_ROOT/backend/contracts/"
log "Staged. Verifying contracts/ is present where app/__init__.py expects it..."
[[ -f "$STAGING_ROOT/backend/contracts/graph_types.py" ]] \
  || die "Staging failed: $STAGING_ROOT/backend/contracts/graph_types.py not found after copy."
log "OK — staged tree has contracts/ nested inside the uploaded backend/ directory."

# --- deploy ----------------------------------------------------------------

log "Deploying $GHAROS_API_SERVICE from staged source (backend/ + contracts/, no Dockerfile)..."
log "Runtime env vars: $BACKEND_ENV_VARS"
gcloud run deploy "$GHAROS_API_SERVICE" \
  --source "$STAGING_ROOT/backend" \
  --project "$project_id" \
  --region "$GHAROS_REGION" \
  --min-instances=0 \
  --max-instances="$MAX_INSTANCES" \
  --allow-unauthenticated \
  --set-env-vars="$BACKEND_ENV_VARS" \
  --quiet

service_url="$(gcloud run services describe "$GHAROS_API_SERVICE" \
  --project "$project_id" --region "$GHAROS_REGION" --format='value(status.url)')"

echo "=================================================================="
log "Deployed: $GHAROS_API_SERVICE"
log "URL:      $service_url"
log "Verify buildpack (not Docker) build: gcloud run revisions describe <revision> --region=$GHAROS_REGION"
log "Next:     ./infra/pubsub_topics.sh   (wires the heartbeat push subscription now that a service URL exists)"
log "Remember: ./infra/teardown.sh after capturing deployment proof (docs/DEPLOYMENT_PROOF.md)."
echo "=================================================================="
