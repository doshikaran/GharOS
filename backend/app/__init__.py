"""GharOS backend application package.

`contracts/` lives one level up from `backend/` (repo root), owned by the
CTO, and is not an installable package in its own right (no pyproject.toml
of its own — PHASES.md §0.1 deliberately keeps it a plain, dependency-free
directory so it stays importable in isolation). Every submodule under
`app/` needs `import contracts...` to resolve regardless of how the process
was started (`uv run uvicorn ...`, `uv run pytest`, a Cloud Run source
deploy), so the repo root is added to `sys.path` here, once, the first time
`app` itself is imported — before any submodule needs it.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
