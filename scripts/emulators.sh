#!/usr/bin/env bash
# GharOS — local Firestore + Pub/Sub emulators (gharos-standards skill,
# cost rule 5: local development uses emulators, no cloud spend day to day).
#
# Starts both emulators as background processes, writes their PIDs to
# .emulator-pids/ (repo-root-relative, gitignored) so `scripts/stop_emulators.sh`-
# style cleanup or a plain `kill $(cat .emulator-pids/*.pid)` works, and prints
# the exact FIRESTORE_EMULATOR_HOST / PUBSUB_EMULATOR_HOST values to export —
# these match `.env.example` at the repo root.
#
# Requires: gcloud CLI (present) with the `cloud-firestore-emulator`,
# `pubsub-emulator`, and `beta` components (this script installs them if
# missing — non-interactive, no sudo required) and a JRE (both emulators are
# JVM-based). If Homebrew's openjdk is present but not the system default,
# this script prepends it to PATH for the emulator processes only; it does
# not modify your shell profile or run `sudo ln -sfn ... /Library/Java/...`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GCLOUD="${GCLOUD:-gcloud}"
FIRESTORE_PORT="${FIRESTORE_PORT:-8080}"
PUBSUB_PORT="${PUBSUB_PORT:-8085}"
PIDS_DIR="${REPO_ROOT}/.emulator-pids"
LOGS_DIR="${REPO_ROOT}/.emulator-logs"

mkdir -p "${PIDS_DIR}" "${LOGS_DIR}"

# --- Java runtime -----------------------------------------------------------
# Both emulators are JVM-based. `command -v java` is not enough on macOS:
# /usr/bin/java exists even with no JRE installed and only errors when you
# actually run it ("Unable to locate a Java Runtime"). So actually invoke
# `java -version` and fall back to Homebrew's keg-only openjdk (which is not
# symlinked onto PATH by design) without touching the system default —
# keeps this script non-interactive and sudo-free.
if ! java -version >/dev/null 2>&1; then
  if [ -x /opt/homebrew/opt/openjdk/bin/java ]; then
    export PATH="/opt/homebrew/opt/openjdk/bin:${PATH}"
  elif [ -x /usr/local/opt/openjdk/bin/java ]; then
    export PATH="/usr/local/opt/openjdk/bin:${PATH}"
  else
    echo "ERROR: no working Java runtime found (checked 'java -version' and" >&2
    echo "        Homebrew's openjdk keg at /opt/homebrew/opt/openjdk and" >&2
    echo "        /usr/local/opt/openjdk). Install one, e.g.: brew install openjdk" >&2
    exit 1
  fi
fi
if ! java -version >/dev/null 2>&1; then
  echo "ERROR: java still not runnable after adjusting PATH — see above." >&2
  exit 1
fi

# --- gcloud emulator components ---------------------------------------------
missing_components=()
"${GCLOUD}" components list --filter="id:cloud-firestore-emulator" --format="value(state.name)" 2>/dev/null \
  | grep -q "Installed" || missing_components+=("cloud-firestore-emulator")
"${GCLOUD}" components list --filter="id:pubsub-emulator" --format="value(state.name)" 2>/dev/null \
  | grep -q "Installed" || missing_components+=("pubsub-emulator")
"${GCLOUD}" components list --filter="id:beta" --format="value(state.name)" 2>/dev/null \
  | grep -q "Installed" || missing_components+=("beta")

if [ "${#missing_components[@]}" -gt 0 ]; then
  echo "Installing missing gcloud components: ${missing_components[*]}"
  if ! "${GCLOUD}" components install "${missing_components[@]}" -q; then
    echo "ERROR: 'gcloud components install ${missing_components[*]}' failed." >&2
    echo "        This usually means the gcloud SDK's own Python bootstrap needs" >&2
    echo "        an interactive step this script can't complete non-interactively." >&2
    echo "        Run it yourself: gcloud components install ${missing_components[*]}" >&2
    exit 1
  fi
fi

# --- start Firestore emulator ------------------------------------------------
echo "Starting Firestore emulator on localhost:${FIRESTORE_PORT} ..."
nohup "${GCLOUD}" emulators firestore start \
  --host-port="localhost:${FIRESTORE_PORT}" \
  --database-mode=firestore-native \
  > "${LOGS_DIR}/firestore.log" 2>&1 &
echo $! > "${PIDS_DIR}/firestore.pid"

# --- start Pub/Sub emulator --------------------------------------------------
echo "Starting Pub/Sub emulator on localhost:${PUBSUB_PORT} ..."
nohup "${GCLOUD}" beta emulators pubsub start \
  --host-port="localhost:${PUBSUB_PORT}" \
  --project=gharos-local \
  > "${LOGS_DIR}/pubsub.log" 2>&1 &
echo $! > "${PIDS_DIR}/pubsub.pid"

# --- wait for both ports to come up -----------------------------------------
wait_for_port() {
  local port="$1" name="$2" tries=0
  while ! lsof -i ":${port}" >/dev/null 2>&1; do
    tries=$((tries + 1))
    if [ "${tries}" -gt 30 ]; then
      echo "ERROR: ${name} emulator did not open port ${port} within 30s." >&2
      echo "        Check ${LOGS_DIR}/${name}.log" >&2
      exit 1
    fi
    sleep 1
  done
}
wait_for_port "${FIRESTORE_PORT}" firestore
wait_for_port "${PUBSUB_PORT}" pubsub

cat <<EOF

Both emulators are up.
  Firestore PID ${PIDS_DIR}/firestore.pid — log: ${LOGS_DIR}/firestore.log
  Pub/Sub   PID ${PIDS_DIR}/pubsub.pid    — log: ${LOGS_DIR}/pubsub.log

Export these (matching .env.example) before running the backend:

  export FIRESTORE_EMULATOR_HOST=localhost:${FIRESTORE_PORT}
  export PUBSUB_EMULATOR_HOST=localhost:${PUBSUB_PORT}

Stop both with:

  kill \$(cat "${PIDS_DIR}"/*.pid) 2>/dev/null; rm -f "${PIDS_DIR}"/*.pid
EOF
