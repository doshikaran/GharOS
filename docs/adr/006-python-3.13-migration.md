# ADR-006: Migrate backend from Python 3.12 to 3.13

**Status:** accepted
**Phase:** 2
**Date:** 2026-08-22

## Context

`PHASES.md` §3 fixed the backend on Python 3.12 at project start. Attempting the first real Cloud Run source deploy (Phase 2, `infra/deploy_backend.sh`) failed at the buildpack build step:

```
Failed to resolve version 3.12 for Python from region asia-south1: failed to resolve
version matching: 3.12 against [3.14.6 3.14.5 ... 3.13.0]
invalid Python version specified: ... Version constraint "3.12" not satisfied by any
available versions in Artifact Registry.
```

Google Cloud's buildpack builder (`google-24-full/builder/universal`) no longer offers Python 3.12 at all — only 3.13.x (down to 3.13.0) and 3.14.x are available. This is a runtime availability change on Google's side since the project's tech stack was fixed, not a defect in any code written so far. Since **no Dockerfile is permitted in this project** (PHASES.md's own non-negotiable, "No Docker. Ever."), there is no way to pin an older Python via a custom base image — the buildpack's own supported version list is the hard constraint.

## Decision

Migrate the backend to **Python 3.13** (specifically letting buildpacks resolve to the latest available 3.13.x — currently 3.13.14 in the builder's list, 3.13.15 available locally via Homebrew). This is the most conservative available option: closer to the original 3.12 pin than 3.14, and a fully released, stable version (not 3.14's beta/RC territory relative to this project's timeline).

Changed:
- `backend/.python-version`: `3.12` → `3.13`
- `backend/pyproject.toml`: `requires-python = ">=3.12"` → `>=3.13`
- Local dev venv rebuilt against Python 3.13.15 (`uv python pin 3.13` / `uv sync`)
- `PHASES.md` §3 (Tech Stack table) and `CLAUDE.md`'s tech stack line updated — both CTO-owned, both corrected in place since they are living build references, not a historical record (unlike this ADR log itself)
- Every `.claude/agents/*.md` and `.claude/skills/*/SKILL.md` reference to "Python 3.12" corrected to "Python 3.13"

## Alternatives considered

1. **Pin an older buildpack builder image that still supports 3.12**, via `--builder` on `gcloud run deploy`. Rejected: Google periodically deprecates old builder images entirely (removes them from the registry, not just stops recommending them) — pinning one now would very likely break again, later, less predictably, and closer to the hackathon deadline than now. It also silently reintroduces exactly the kind of "the demo works today but nobody can reproduce it in three months" fragility the project's own reproducibility requirement (spec §3.2, "Demo & Production Readiness") exists to avoid.
2. **Write a Dockerfile pinning Python 3.12 exactly.** Rejected outright — violates the project's own non-negotiable "No Docker. Ever." (PHASES.md Appendix D rule 5). Not seriously considered as an option; noted here only so the record shows it was recognized and rejected on principle, not overlooked.
3. **Move to Python 3.14** instead of 3.13. Rejected for now: 3.13 is the smaller, more conservative version delta from the original 3.12 pin, minimizing behavioral-change surface for the rest of the build with no offsetting benefit — nothing in this project currently needs a 3.14-only feature.

## Consequences

- All 70 backend source files were re-verified clean (`mypy --strict`, `ruff check`, full `pytest` suite — 184 passed / 8 skipped, unchanged) under Python 3.13 before this ADR was finalized — the migration did not silently break anything.
- `backend/.venv` was rebuilt; any other machine (or CI, once one exists) picking up this repo needs `uv sync` to pick up 3.13 via `.python-version`, same as always — no change to the dev workflow itself.
- Future gate reviews and the `gharos-standards` skill should read "Python 3.13" as the current pin, not 3.12 — corrected everywhere at the time of this ADR (see Decision section for the exact file list).
- If Google's buildpack builder later drops 3.13 too, the same triage applies: check the builder's currently-offered version list (visible in the exact same build-log error format) and repeat this process with a new ADR, rather than treating a past pin as permanent.
