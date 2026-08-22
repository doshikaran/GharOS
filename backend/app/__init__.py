"""GharOS backend application package.

`contracts/` is owned by the CTO and is not an installable package in its
own right (no pyproject.toml of its own — PHASES.md §0.1 deliberately keeps
it a plain, dependency-free directory so it stays importable in isolation).
Every submodule under `app/` needs `import contracts...` to resolve
regardless of how the process was started — and, critically, regardless of
`contracts/`'s depth relative to this file, which is NOT constant:

- Local dev (`uv run uvicorn ...`, `uv run pytest`): `contracts/` is two
  directories above this file (`backend/app/__init__.py` -> `backend/` ->
  the real repo root, which contains `contracts/`).
- A Cloud Run source deploy (`infra/deploy_backend.sh`, ADR-007): only ONE
  directory is ever uploaded as the build context, so the deploy script
  stages a copy of `contracts/` *inside* the uploaded tree, one directory
  above this file, not two (`/workspace/app/__init__.py` ->
  `/workspace/`, which contains the staged `contracts/`).

A fixed `parents[N]` index is therefore wrong for at least one of these two
real deployment shapes — this was discovered the hard way in Phase 2 (a
hardcoded `parents[2]` broke the very first production deploy with
`ModuleNotFoundError: No module named 'contracts'`, silently correct in
every local test that ran the same code from the same relative depth). The
fix is to search upward from this file for whichever ancestor directory
actually contains `contracts/`, bounded to a small number of levels so a
missing `contracts/` fails fast and loudly rather than silently walking to
the filesystem root.
"""

from __future__ import annotations

import sys
from pathlib import Path

_MAX_LEVELS_UP = 4
_START = Path(__file__).resolve().parent  # backend/app/


def _find_contracts_root(start: Path, max_levels: int) -> Path:
    """Walks upward from `start` looking for an ancestor directory that
    contains `contracts/graph_types.py` — a specific-enough marker that a
    directory merely named `contracts` for an unrelated reason won't false-
    positive. Raises `RuntimeError` (loudly, at import time, not a silent
    `ImportError` deep in some unrelated submodule) if none is found within
    `max_levels` — this must never fail silently, since every submodule in
    this package depends on it having succeeded."""
    candidate = start
    for _ in range(max_levels + 1):
        if (candidate / "contracts" / "graph_types.py").is_file():
            return candidate
        if candidate.parent == candidate:  # reached filesystem root
            break
        candidate = candidate.parent
    raise RuntimeError(
        f"Could not find a 'contracts/graph_types.py' within {max_levels} "
        f"directories above {start}. `contracts/` must be reachable either "
        "as a real repo sibling of backend/ (local dev) or staged inside "
        "the deploy upload (infra/deploy_backend.sh, ADR-007)."
    )


_CONTRACTS_ROOT = _find_contracts_root(_START, _MAX_LEVELS_UP)
if str(_CONTRACTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_CONTRACTS_ROOT))
