"""The honest evaluation (PHASES.md Phase 4, "The honest evaluation").

Not a unit-test package in the usual sense — this directory holds A12's
held-out evaluation harness: twenty hand-authored, hand-verified messy
documents (`held_out_documents.py`) A12 was never tuned against, and the
runner that scores real Gemini output against them (`implication_eval.py`).
Its default-suite footprint is deliberately small (a handful of free,
offline data-integrity checks); the actual live-Gemini run is `live_gcp`-
marked, exactly like every other real-network test in this repo
(`GHAROS_RUN_LIVE_GCP_TESTS=1 GCP_PROJECT_ID=... uv run pytest -m live_gcp`).

See `docs/IMPLICATION_BASELINE.md` for the recorded numbers from the real
run this harness produced.
"""

from __future__ import annotations
