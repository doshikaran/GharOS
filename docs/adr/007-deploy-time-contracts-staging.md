# ADR-007: Stage `contracts/` inside the deploy upload, and resolve it by upward search

**Status:** accepted
**Phase:** 2
**Date:** 2026-08-22

## Context

`contracts/` lives at the repo root as a sibling of `backend/`, deliberately not an installable package (no `pyproject.toml` of its own — PHASES.md §0.1 keeps it a plain, dependency-free directory importable in isolation, so `backend/`, `frontend/`, and any future consumer share the exact same frozen types without a packaging/versioning layer between them). `backend/app/__init__.py` originally resolved it locally via a `sys.path` insert of a fixed ancestor: `Path(__file__).resolve().parents[2]` — two directories above `backend/app/`, which is the real repo root in local dev.

The first real `infra/deploy_backend.sh` run (Phase 2) crashed the deployed container at import time: `ModuleNotFoundError: No module named 'contracts'`. Root cause: `gcloud run deploy --source ./backend` uploads exactly one directory as the buildpack build context — `backend/`'s own contents become the container's `/workspace/`. `contracts/`, a sibling of `backend/` on disk, is not inside that directory, so it never reaches the container regardless of what happens outside the upload.

**A first fix attempt was itself wrong** and is worth recording precisely because the mistake is easy to repeat: staging a copy of `contracts/` as a *sibling* of the staged `backend/` directory (i.e. `$STAGING/backend/` + `$STAGING/contracts/`, mirroring the real repo's relative layout) still fails, because `--source "$STAGING/backend"` uploads only `$STAGING/backend`'s contents — `$STAGING/contracts` is a sibling of the *upload root*, not inside it, and is silently never uploaded. The bug reproduced identically after that first fix, which is what caught the mistake before it shipped.

## Decision

Two changes together, not one:

1. **`infra/deploy_backend.sh` stages `contracts/` INSIDE the uploaded tree**: `$STAGING/backend/contracts/` (nested, one level below the upload root), not alongside it. The staging directory is created via `mktemp -d` and removed via `trap ... EXIT`.
2. **`backend/app/__init__.py` resolves `contracts/`'s location by upward search, not a hardcoded depth.** `contracts/` sits at a genuinely different relative depth from `app/__init__.py` in the two real deployment shapes this project has — two directories up in local dev (repo root), one directory up in a deploy (the upload root, since the staged copy is nested one level in). A single fixed `parents[N]` index cannot be correct for both. `_find_contracts_root()` walks upward from `app/__init__.py`'s location, up to a small bounded number of levels, looking for an ancestor containing `contracts/graph_types.py` (a specific marker file, not just a directory named `contracts`), and raises loudly at import time if none is found — never silently walking to the filesystem root or masking the failure as an unrelated `ImportError` somewhere deep in a submodule.

Together, this means `contracts/`'s single-source-of-truth property stays intact (the staged copy is disposable, regenerated fresh on every deploy, never edited in place — there remains exactly one real `contracts/`), and the resolution logic is now correct for both the current two known layouts and any future one, without needing another ADR every time a build/deploy mechanism changes.

## Alternatives considered

1. **Move `contracts/` inside `backend/` permanently** (e.g. `backend/contracts/`), so a plain, un-staged `--source ./backend` upload includes it natively. Rejected: `contracts/` is explicitly shared, frozen infrastructure the whole project depends on, not a backend implementation detail — PHASES.md's repo structure places it at the root precisely so it reads as "the contract every role builds to." Moving it would also break the mental model (and, eventually, any frontend codegen step) that treats it as root-level, for a problem that is really about deploy tooling, not code organization.
2. **A git submodule or an installable local package for `contracts/`** (a `file://` path dependency in `backend/pyproject.toml`). Rejected as overkill at this project's single-repo, single-team scale: a `file://` dependency still needs `contracts/` reachable at the path it names relative to the build context — the same "make a copy available to the upload" problem this ADR solves, with more machinery (a second `pyproject.toml`, a version number for a package meant to be frozen-by-fiat) and no real benefit.
3. **A symlink from `backend/contracts` to `../contracts`, committed to git.** Rejected: `gcloud run deploy --source` tars the specified directory for upload; a symlink pointing outside that directory either isn't followed (a dangling link in the container) or has platform-dependent behavior. Explicit staging with a real copy is unambiguous.
4. **Keep the fixed `parents[2]` index and just fix the staging depth to match it** (i.e. make the deploy script produce a tree three levels deep so `parents[2]` still lands on the right ancestor). Rejected: this recreates the exact fragility that caused the bug in the first place — the sys.path logic would still be silently coupled to one specific deploy script's directory choices, and a future change to either side (the deploy script's staging depth, or Cloud Run's own upload semantics) could break it again just as invisibly. Upward search removes that coupling entirely.

## Consequences

- Every future deploy of `gharos-api` goes through the staging step automatically — no manual step for whoever runs `infra/deploy_backend.sh` next.
- `backend/app/__init__.py`'s resolution logic is now deployment-shape-agnostic: it would work unchanged even if a future deploy mechanism nested things differently, as long as `contracts/graph_types.py` is reachable within `_MAX_LEVELS_UP` (currently 4) directories above `app/__init__.py`.
- A genuinely missing `contracts/` (e.g. a broken staging step) now fails loudly and immediately at import time with a clear `RuntimeError` naming exactly what was searched, instead of manifesting later as a cryptic `ModuleNotFoundError` deep inside whichever submodule happened to `import contracts` first.
- Local development (`uv run uvicorn app.main:app`, `uv run pytest`) is unaffected in behavior — the upward search still finds the real repo root's `contracts/` at the same depth it always resolved to, just via search instead of a hardcoded index.
- `infra/deploy_frontend.sh` has no equivalent problem: the frontend doesn't import Python `contracts/` types directly. If a future phase adds a build-time codegen step deriving frontend types from `contracts/`, that step needs its own "make `contracts/` reachable to the build" consideration — noted here so it isn't rediscovered from scratch.
