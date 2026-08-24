# ADR-010: Per-tier Vertex AI location routing

**Status:** accepted
**Phase:** 4
**Date:** 2026-08-24

## Context

DEBT-003 (opened Phase 2): live-tested Vertex AI calls against `blissful-trail-506312-t0` showed `gemini-2.5-flash` works correctly in `asia-south1`, but `gemini-2.5-pro` 404s in that same region after ~15 model-id variants tried, while working correctly via Vertex AI's `"global"` location. This is a real, asymmetric Model Garden availability gap on this project — not a naming defect, not fixable by changing the model id. Phase 4's flagship agent (A12 Implication Agent) is Pro-tier and cannot function until Pro-tier calls actually succeed.

## Decision

`ModelRouter` now takes a separate `location_pro` parameter alongside `location`, defaulting to `location` when not given (single-region routing stays the default for any future project where regional Pro-tier access exists). `Settings.vertex_ai_location_pro` (default `"global"`) supplies it in this project. `route()` picks `location_pro` for `ModelTier.PRO` requests and `location` for everything else — Flash stays regional for latency, since it has no availability gap to work around.

Verified live: a real Pro-tier call (`gemini-2.5-pro`, `AgentId("A12")`) through the fixed router succeeded, returning a real model response, via `location="global"`.

## Alternatives considered

1. **Request/confirm regional Pro-tier access for this project** (DEBT-003's other named option). Rejected for now: this requires action outside this session's control (a Google Cloud quota/access request with an unknown turnaround), and blocks Phase 4 from starting at all in the meantime. If regional access is ever granted, the fix is a one-line settings change (`VERTEX_AI_LOCATION_PRO=asia-south1`), not a code change — this decision doesn't foreclose that path.
2. **Route everything through `"global"`**, including Flash. Rejected: Flash has no availability gap in `asia-south1`, and a single shared global endpoint adds latency with no offsetting benefit for the high-volume ingestion/routing/classification calls Flash actually handles (spec §21.1's cost/latency discipline).

## Consequences

- `ModelRouter`'s constructor signature changed (additive — `location_pro` is optional, defaults preserve prior single-region behavior for any caller that doesn't pass it). The one production call site (`backend/app/api/debug.py:get_model_router`) updated to pass `settings.vertex_ai_location_pro`.
- Every LLM-backed agent built from Phase 3 onward that goes through `ModelRouter` (which is all of them, by design — see `model_router.py`'s own module docstring) gets this fix automatically; no per-agent changes needed.
- `test_model_router.py` gained three tests proving per-tier location routing, plus a fix to an existing test that had silently drifted: `test_every_currently_allowlisted_agent_can_route_pro_tier` claimed to test "every" allowlisted agent but used a hand-copied literal list that Phase 3's allowlist additions (A3, A3b, A3c) never got added to — now parametrized directly off the live `PRO_TIER_ALLOWLIST` set so this can't silently drift again.
- DEBT-003 is resolved — struck in `docs/DEBT.md` with this ADR as the resolution record.
