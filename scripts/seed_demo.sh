#!/usr/bin/env bash
# GharOS — scripts/seed_demo.sh
#
# Operator-facing wrapper over `python -m seeds` (backend/seeds/cli.py,
# PHASES.md Phase 15 / spec §24 / §26). Loads — or wipes and reloads —
# the full 4-minute-demo household into a running Firestore, always
# through the real provenance-guarded `FirestoreGraphWriter`
# (`seeds.seed_loader.load_full_demo`), never by writing to Firestore
# directly. The CLI verifies the result (`unexplained("all")` empty +
# integrity checker clean) and exits non-zero on a broken graph, so
# `make seed-demo` fails loudly rather than leaving something half-built.
#
# Usage:
#   ./scripts/seed_demo.sh              # = `load` — write the demo dataset
#   ./scripts/seed_demo.sh load
#   ./scripts/seed_demo.sh reset        # wipe every graph collection, then reload
#   ./scripts/seed_demo.sh reset --yes-live   # allow reset against REAL Firestore
#
# `make seed-demo` runs the no-arg form. Re-run `reset` between rehearsals
# so the graph-growth beat starts from a clean pre-trigger baseline
# (DEMO_SCRIPT.md §0.1).
#
# Defaults FIRESTORE_EMULATOR_HOST / PUBSUB_EMULATOR_HOST to the local
# emulator ports (matching .env.example) when they are not already set,
# and refuses to run if the Firestore emulator is not reachable — unless
# you are deliberately targeting real Firestore with `reset --yes-live`.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${REPO_ROOT}"

# --- emulator host defaults (match .env.example) --------------------------
export FIRESTORE_EMULATOR_HOST="${FIRESTORE_EMULATOR_HOST:-localhost:8080}"
export PUBSUB_EMULATOR_HOST="${PUBSUB_EMULATOR_HOST:-localhost:8085}"

FIRESTORE_HOST="${FIRESTORE_EMULATOR_HOST}"

# `reset --yes-live` is the only path allowed to target real Firestore;
# every other invocation requires a reachable emulator so a stray
# `make seed-demo` can never touch a live project.
targeting_live=0
if [[ "${1:-}" == "reset" ]]; then
  for arg in "$@"; do
    [[ "${arg}" == "--yes-live" ]] && targeting_live=1
  done
fi

if [[ "${targeting_live}" -eq 0 ]]; then
  if ! curl -fsS -o /dev/null --max-time 3 "http://${FIRESTORE_HOST}/" 2>/dev/null; then
    echo "ERROR: Firestore emulator not reachable at ${FIRESTORE_HOST}." >&2
    echo "       Start it first:  make emulators" >&2
    echo "       (or run 'reset --yes-live' to target real Firestore deliberately)" >&2
    exit 1
  fi
fi

# --- run the CLI --------------------------------------------------------
# Default subcommand is `load`. Anything the caller passes is forwarded
# verbatim (load / reset / reset --yes-live).
if [[ "$#" -eq 0 ]]; then
  set -- load
fi

echo "seed_demo: python -m seeds $* (FIRESTORE_EMULATOR_HOST=${FIRESTORE_EMULATOR_HOST})"
cd "${REPO_ROOT}/backend"
exec uv run python -m seeds "$@"
