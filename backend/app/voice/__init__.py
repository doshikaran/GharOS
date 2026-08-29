"""Inbound voice infrastructure agents (A62, A63, A66, A69 — spec §14,
§15.11, PHASES.md Phase 13, ADR-020) — E3's `backend/app/voice/`.

**Scope.** This package holds the four *infrastructure* agents in the
inbound voice pipeline: session orchestration (A62), streaming ASR (A63),
speaker identification (A66), and TTS response generation (A69). It does
not hold the four *reasoning* agents (A64 language/script identification,
A65 normalisation, A67 intent classification, A68 confirmation) — those
are E2's `backend/app/agents/voice/` (ADR-020 Decision 3/5). Mirrors the
split `backend/app/agents/concierge/` (E2) vs `backend/app/arbitration/` +
this package (E3) already established for A50/A52/A53/A55 vs
A51/A54/A56 in Phase 10.

**Safety invariant 8 (voice confers no action capability).** `A63`
(`speech_recognition_handler.py`), `A66` (`speaker_identification.py`),
and `A69` (`voice_response_agent.py`) hold no import path to
`app.arbitration` and construct no `contracts.tools.ApprovalGatedTool` —
proven by `backend/tests/test_voice_infra_arbitration_boundary.py`,
mirroring E2's own `test_voice_agents_arbitration_boundary.py` technique
exactly. **`session_manager.py` and `routing.py` (both A62) are the
deliberate exception** — `routing.py` is the single place in this whole
voice subsystem that holds an `ApprovalGate` reference (`session_types.py`
carries the shared type vocabulary both need, including a gated-tool
type, and is excluded from the same scan for that reason), per ADR-020
Decision 5 item 3: it calls `request_approval` for any R2/R3-tier intent,
executes directly for R0/R1, and — the safety-critical line — never calls
`approve_and_execute` for an R3-tier request off a voice confirmation
alone. This is what closes safety invariant 8 for real this phase (it
stood as a tracked `@pytest.mark.skip` placeholder since Phase 1).
"""

from __future__ import annotations
