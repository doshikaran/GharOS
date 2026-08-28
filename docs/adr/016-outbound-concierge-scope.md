# ADR-016: Outbound Concierge — real sandbox conversation, audio deferred to Phase 13; no new contract types

**Status:** accepted
**Phase:** 10
**Date:** 2026-08-27

## Context

Spec §13.7's demo beat describes "live call placed and **heard**" — but spec §23 is explicit and binding: "For the demo, call a controlled/sandbox counterparty, not a real business — and say so honestly. Implying a live cold call to a real clinic when it is staged is the kind of overclaim that discredits an otherwise strong submission." Spec §14's own scope note is equally explicit: §13 covers *outbound* voice's orchestration; real ASR/TTS build-out is §14's job, and PHASES.md assigns that build-out to **Phase 13 (Voice & Multilingual)**, three phases from now — no ASR/TTS pipeline exists anywhere in this codebase yet. PHASES.md's own Gate 10 checklist (the actual binding acceptance bar, not spec's demo-beat prose) never uses the word "heard," "audio," "TTS," or "ASR" anywhere in its eight items — every item is about orchestration, bounds, disclosure, and verification, all achievable and testable without synthesized speech.

## Decision

**A54 Voice Call Agent conducts a real, live, multi-turn conversation this phase — in text/transcript form, not synthesized audio.** The call is real in every sense that matters to Gate 10: a real live Gemini-backed turn-taking exchange against a real, independently-reasoning sandbox counterparty persona (built this phase, §13.7's own "controlled/sandbox counterparty"), with real disclosure, real pre-authorised bounds enforced turn-by-turn, real out-of-bounds handling, a real stored transcript, and real post-call verification before anything is written to the graph. The only thing genuinely absent is the audio layer (text-to-speech synthesis and speech recognition) — deferred to Phase 13, which is the phase spec itself assigns that work to, not guessed at or skipped silently.

**This is not a lesser version of the feature — it is the honest version of it.** Building fake TTS/ASR now (or worse, implying live audio exists when it does not) would be exactly the overclaim spec §23 names by name. The real work Gate 10 actually tests — bounds enforcement, disclosure, branch handling, verification-before-recording — is fully real this phase, proven by real tests against a real, independently-behaving counterparty, not a scripted fixture.

**The sandbox counterparty is a real, second LLM-backed agent, not a canned response table.** It holds its own persona (a dental clinic front desk, for the reference scenario), its own state (available slots, whether it asks an unanswerable question, whether a requested slot is actually available), and reasons about its own turns independently of A54 — so A54's bounds-checking and branch-handling are tested against genuine, LLM-generated variation, not a fixture the calling agent's own code effectively wrote both sides of.

## Decision — no new contract types

Checked directly before writing anything: `Provider` (rating, distance_km, availability_notes, price_band, specialisations), `EdgeType.BOOKED_WITH` (OBLIGATION → PROVIDER), `SourceDocument` (channel, raw_payload_ref — a call transcript is a `SourceDocument` with `channel="voice_call_outbound"`, its `raw_payload_ref` pointing at the stored transcript text via the existing `RawPayloadStore`, Phase 3), and `Outcome` (`predicted`, `actual`, `variance`, `attribution_tags: tuple[str, ...]`) already cover every graph-write spec §13.5 names — all frozen since Phase 0/1, all still fit for purpose. `PermissionTier.T5_VOICE_OUTBOUND` is already a `GATED_TIERS` member (frozen since Phase 0) — the Approval Gate mechanism this phase's call needs is Phase 5's, unchanged, exactly the precedent `SandboxPaymentTool` (T6, Phase 7) already set for a new gated tool built on existing arbitration machinery.

**One formalized convention, not a contract change:** `Outcome.attribution_tags` gets a defined vocabulary for provider-reliability signals this phase introduces real writers for — `"no_show"`, `"on_time"`, `"rescheduled"`, `"unresponsive_to_automated_caller"` — so A52 Provider Ranking's "prior-experience weighting... a provider who no-showed before is demoted" has a stable, queryable signal to look for (via `booked_with` → the obligation's `completes_into` `Outcome` → its `attribution_tags`) rather than free-text pattern-matching. This is a documented convention (like ADR-015's `SCHEDULE` structured-key schema), not a `contracts/graph_types.py` field addition.

## Alternatives considered

1. **A scripted/fixture-driven sandbox counterparty** (a decision tree of canned responses). Rejected: this would make A54's own branch-handling logic effectively self-testing (the same engineer's code on both sides of the conversation), and would not exercise real turn-taking judgment under genuine uncertainty the way a second, independently-reasoning agent does.
2. **Building minimal TTS/ASR now** to literally satisfy spec's demo-beat prose. Rejected: PHASES.md assigns this to Phase 13 for a reason (it is real, substantial infrastructure — streaming ASR, code-mix-tolerant, four languages — not a quick add), and Gate 10's own checklist never requires it. Building a thin, non-production version now would risk exactly the "overclaimed integration" pattern `.claude/agents/e3.md` warns discredits a submission, and would need redoing properly in Phase 13 anyway.
3. **A new `CallTranscript` graph node type.** Rejected: `SourceDocument` already is exactly this (a raw payload plus channel plus provenance) — every other document type in this system, however different in origin, reduces to a `SourceDocument`; a call transcript is not structurally different.

## Consequences

No change to `contracts/graph_types.py` or `contracts/tools.py` this phase — the frozen shapes from Phase 0 already fit. E3 builds the sandbox counterparty persona and the real T5 `ApprovalGatedTool` (mirroring `SandboxPaymentTool`'s established shape). E2's A52 Provider Ranking builds real, tested queries against the `attribution_tags` convention above. Every demo-facing surface (E4's UI, this phase's own `verification.md` section) must state plainly that the call is a real, live, sandboxed conversation in transcript form — never implying synthesized audio exists yet.
