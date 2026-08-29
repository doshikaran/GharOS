# ADR-020: Voice & Multilingual — ASR viability, language depth split, inbound-voice architecture

**Status:** accepted
**Phase:** 13
**Date:** 2026-08-29

## Context

Phase 13's own charter is explicit: "Test intra-sentential Hinglish ASR in the first hours of this phase. It gates everything here (spec open question #13). If unusable out of the box, escalate to the CTO for a scope call immediately." This ADR records that test and the scope decisions it and the rest of spec §13.3/§14 require, before any of E2/E3/E4's Phase 13 work begins.

Checked directly against `contracts/` before writing anything: this codebase's contracts were built with Phase 13 in view since Phase 0/1 —

- `contracts/graph_types.py`'s `LanguageProfile` (`primary_language`, `languages_understood`, `script_preference`, `code_mixing_profile`, `formality_preference`, `literacy_mode`) already exists on `Person.language_profile`, matching spec §14.3 field-for-field. `Person.voiceprint_ref` and `Person.pronunciation_hints` already exist for A66/A69.
- `contracts/tools.py`'s `PermissionTier.T5I_VOICE_INBOUND` already exists, already carries the exact spec §16 invariant-8 docstring ("Confers NO action capability of its own"), and is correctly **excluded** from `GATED_TIERS` — T5i is read/perceive-only (ASR, TTS, speaker-ID), never a gated write/send/pay path.
- `contracts/graph_types.py`'s `SourceDocument` (`channel: str`, `raw_payload_ref: str`, `original_language: str | None`) is already channel-agnostic — `channel="voice"` and a stored audio blob ref fit with zero shape change, exactly as `channel="email"`/`"whatsapp"` do today.

**Decision: zero new node types, zero new edge types, zero changes to `contracts/graph_types.py` or `contracts/tools.py` this phase.** This is a real finding, not an oversight to flag — Phase 13's contract surface was correctly anticipated three phases in advance.

## Decision 1 — real ASR viability test, run against live Vertex AI before any code was written

Per the charter's own instruction, the test was run first. Three short household-register test utterances were synthesized (macOS `say`, Hindi voice for the Devanagari-script rendering of the Hindi/English mix, a plain-English control) and sent as real audio bytes through a live `google-genai` Vertex AI call (`gemini-2.5-pro`, `global` location per ADR-010) with a prompt instructing verbatim, non-normalizing transcription:

| Input (spoken) | Model output |
|---|---|
| "Aarav ko Friday ko field trip hai, permission slip sign karna hai aur paise dene hai" | "Aarav ko Friday ko field trip hai. Permission slip sign karna hai aur paise dene hain." |
| "Society maintenance cha payment kela ka" | "Society maintenance cha payment ke la ka" (minor word-boundary split, content preserved) |
| Plain English control | Transcribed cleanly, unchanged register |

**Result: GO.** The model did not translate or normalize into fluent monolingual English — it preserved the code-mixed structure exactly as spoken, satisfying A63's forbidden-list constraint ("cleaning up transcripts into fluent monolingual text... destroys the code-mixing signal"). This is a synthesized-speech proxy, not a real-household-recording test — honestly scoped as such — but it answers the charter's actual gating question (does an out-of-the-box path exist that doesn't collapse code-switching) with a real live call, not a guess. No scope-kill escalation needed.

**Architectural consequence:** A63 Speech Recognition Handler is built on the existing `GeminiClient.generate_multimodal` (`reasoning/gemini_client.py`, already accepts a `MediaPart(data: bytes, mime_type: str)` — built for image/PDF bytes in Phase 3, generically byte-agnostic, audio bytes flow through the identical path) rather than a separate speech-to-text product (Google Cloud Speech-to-Text). This is a deliberate choice, not a default: Vertex AI's own real-time multimodal understanding demonstrably preserves code-mixing in this test; a dedicated STT engine's job is normally to *force* a single-language grammar and would fail A63's own forbidden-list requirement by design.

**Honest limitation, same category as Phase 6's browser-paint caveat:** Vertex AI's `generateContent` audio path does not expose true acoustic per-token confidence/logprobs the way a dedicated streaming STT API does. A63's "per-token confidence" (spec §15.11 A63 output contract) is therefore a **per-span, model-self-reported confidence** — the model is prompted to flag its own uncertain spans explicitly, the same self-reported-confidence discipline this codebase already uses for A57 Confidence Arbiter's borderline-score escalation. This is disclosed in A63's own module docstring, not silently presented as acoustic confidence.

## Decision 2 — language depth split, per the phase's own recommended review question

Confirmed with the operator directly: **English + Hindi/Hinglish at full depth (Class A, the hard case); Marathi + Spanish at demonstration breadth (Class B for Spanish; Marathi gets the same code-mixing machinery as Hindi, since A64 must already disambiguate the two lexically/grammatically, but does not receive Hindi's dedicated tuning/prompt iteration time).** No deviation from spec §14.2's fixed four-language set — no French, no dropped language.

**Consequence:** A64 Language & Script Identifier's Hindi/Marathi disambiguation prompt is written and iterated against real test cases for both; A65 Normalisation's kinship-term and lakh/crore handling gets full coverage for Hindi/Marathi and Spanish's own number/date formats; A69 TTS voice selection covers all four languages, but demo-beat rehearsal time (Phase 14's mandatory ≥3 runs) is not expected to feature Marathi/Spanish beyond one clean beat each, matching Gate 13's own review guidance ("two excellent beats beat four shaky ones").

## Decision 3 — inbound voice is a browser session, not a telephony line; "Mic/telephony wiring" scoped honestly

Spec §14 (inbound, this phase) is a different channel from spec §13 (outbound calling, Phase 10's `A54`/sandbox counterparty). Inbound voice is the household talking *to* GharOS through the product's own surface — there is no PSTN leg on this side at all, and no dial-in number is in scope for the hackathon submission. **"Mic/telephony wiring" (E3 work item) is real browser microphone capture (`MediaRecorder`/Web Audio API, E4) streamed to a real backend WebSocket session endpoint (E3) — not a phone line.** This is the honest, correctly-scoped equivalent of Phase 10's own sandbox-counterparty disclosure: say what's real (a live mic-to-model round trip, real ASR, real TTS playback) rather than implying unbuilt telephony infrastructure.

**Session/message contract** (implementation detail, not a `contracts/` change — this is transport shape between E3's endpoint and E4's client, analogous to how `/graph/stream`'s SSE shape was never formalized in `contracts/` either):

```
Client → Server (binary WebSocket frames, PCM16 mono 16kHz chunks)
Server → Client (JSON text frames):
  {"type": "session_state", "state": "listening"|"processing"|"speaking"|"closed"}
  {"type": "transcript_partial", "spans": [{"text": str, "language": str, "confidence": float}], "turn_id": str}
  {"type": "transcript_final", "spans": [...], "turn_id": str}
  {"type": "confirmation_prompt", "text": str, "requires_affirmative": true, "turn_id": str}
  {"type": "response_audio", "audio_b64": str, "mime_type": "audio/mpeg", "text": str, "language": str, "turn_id": str}
  {"type": "error", "code": str, "message": str}
```

A62 Voice Session Manager owns turn-taking/barge-in/silence-timeout state machine on top of this; a barge-in is the client sending new audio frames while `session_state == "speaking"`, which cancels in-flight TTS playback client-side and reopens a new turn server-side.

## Decision 4 — Pro-tier allowlist additions (E2 executes, listed here for the phase-wide record)

Per spec §15.11's own tier assignments, `reasoning/model_router.py`'s `PRO_TIER_ALLOWLIST` gains four entries this phase: **A65** (ambiguous-amount disambiguation only — Flash remains the default path for unambiguous normalisation, mirroring A3/A5/A13's existing escalate-on-ambiguity pattern), **A67** (intent classification is judgment, not routing-by-keyword), **A68** (confirmation read-back correctness is safety-critical — spec explicitly assigns Pro-tier), **A69** (response generation + register/pacing adaptation). A62/A63/A64/A66 stay Flash-tier (session mechanics, per-span tagging, speaker-ID — high-volume, not hard reasoning), matching spec's own "Flash realtime"/"Flash" assignments for those four.

## Decision 5 — safety invariant 8 closes this phase

`backend/tests/test_safety_invariants.py::test_invariant_8_voice_confers_no_action_capability` has stood as a named `@pytest.mark.skip(reason="implemented in Phase 13")` placeholder since it was written — the same status invariant 6 held until Phase 12. **E3 (lead) closes it for real this phase**, as a structural/import-boundary test in the same family as Phase 12's invariant-6 grep and Phase 7/10/12's arbitration-import boundary tests:

1. **No module under `backend/app/agents/voice/` (A64, A65, A67, A68 — reasoning agents) imports `app.arbitration` at all**, matching the standing "reasoning agents hold no action credentials" discipline already proven for Council (ADR-019 Decision 6) and Phase 7/10's arbitration-import boundary tests. A67/A68 return structured judgments (`VoiceIntentResult`, `ConfirmationResult`) only.
2. A67 Voice Intent Classifier holds no tool with a tier above T2 — it classifies and routes, never executes (spec's own forbidden-list line for A67).
3. **Only the orchestrator (`backend/app/voice/session_manager.py`, E3 — infrastructure, not a reasoning agent, same status as the existing tool-dispatch layer other channels already use) holds the `ApprovalGate` reference.** It calls `request_approval` for any R2/R3-tier `VoiceIntentResult`, executes directly (no gate) for R0/R1 per those tiers' own "Execute; log/notify" policy, and — the safety-critical line — **never calls `approve_and_execute` for a request whose `risk_tier == RiskTier.R3_EXPLICIT_APPROVE` off the back of a voice confirmation alone**, regardless of how affirmative A68's read-back result was. An R3 request from voice is always left `PENDING`, resolved only through the existing visual approval queue (Phase 5) — the concrete mechanism behind spec §14.6 rule 6.
4. Silence/ambiguous response is proven (by test) to never construct an affirmative — A68 requires an explicit, enumerated affirmative-utterance match, not the mere absence of a rejection.

## Consequences

No `contracts/` changes. `docs/PROGRESS.md` and `verification.md` record this ADR at Phase 13's gate. E3 (lead): `backend/app/voice/` (A62 session manager + WS endpoint, A63 ASR via `GeminiClient.generate_multimodal`, A66 speaker-ID, A69 TTS + response synthesis), mic/session wiring, invariant-8 closure. E2: `backend/app/agents/voice/` (A64 language/script identifier, A65 normalisation, A67 intent classifier, A68 confirmation agent) + `backend/app/prompts/a6[4-9]_*`, `model_router.py` allowlist update. E4: voice surface (live transcript with per-span language tags, confirmation prompts, session state) and per-person language profile settings, built against the WebSocket message shape in Decision 3.
