"""Inbound voice reasoning agents (A64, A65, A67, A68 — spec §14, §15.11,
PHASES.md Phase 13, ADR-020) — E2's `backend/app/agents/voice/`.

**Scope.** This package holds the four *reasoning* agents in the inbound
voice pipeline: per-span language identification (A64), normalisation
(A65), intent classification (A67), and read-back confirmation (A68). It
does not hold session mechanics (A62), streaming ASR (A63), speaker
identification (A66), or TTS response generation (A69) — those are E3's
`backend/app/voice/` (ADR-020 Decision 3/5). Mirrors the split
`backend/app/agents/concierge/` already established for A50/A52/A53/A55
(E2) vs A51/A54/A56 (E3) in Phase 10.

**Safety invariant 8 (voice confers no action capability).** None of the
four modules in this package import `app.arbitration`, hold a tool above
T0/T2, or construct a `contracts.actions.Action`. Each agent's own module
docstring states this explicitly; `backend/tests/test_voice_agents_
arbitration_boundary.py` proves it by AST inspection — E2's own,
independently-true half of the invariant. Closing the invariant for real
(wiring the Approval Gate so an R3 request from voice is never resolved
without a visual confirmation) is E3's orchestrator
(`backend/app/voice/session_manager.py`, next wave).
"""

from __future__ import annotations
