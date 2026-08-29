"""Typed errors for `backend/app/agents/voice/` (A64, A65, A67, A68 — spec
§14, §15.11, PHASES.md Phase 13, ADR-020).

Mirrors `app.agents.council.errors`/`app.agents.concierge.errors`'s role
for their own packages deliberately as a separate module, not a shared
import, so this package's error taxonomy stays self-contained (the
established per-package boundary convention).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class VoiceAgentError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/voice/`. Mirrors `app.agents.council.errors.
    CouncilError`'s role for its own package."""


class ModelResponseMalformed(VoiceAgentError):
    """Raised when an LLM-backed voice agent's response cannot be parsed
    into the exact JSON shape its prompt demands, or names something
    structurally impossible (e.g. A67 reporting a risk tier outside the
    set its own intent class permits — see `voice_intent_classifier_
    agent.py`). Never silently reinterpreted as an empty or best-guess
    result (safety invariant #7's analogue here)."""

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


class AmountClarificationRequired(VoiceAgentError):
    """Raised by nothing in normal operation — reserved for a caller
    (E3's orchestrator) that wants a hard failure rather than reading
    `NormalizedSpan.needs_clarification` off the result. A65 itself never
    raises this; it always returns a `NormalizationResult` with the
    ambiguous span flagged, per spec's own "always clarify, never round
    or guess" failure-mode rule — this class exists only so a stricter
    caller has a typed exception available without this package inventing
    a second parallel signalling mechanism."""

    def __init__(self, *, turn_id: str, span_text: str) -> None:
        self.turn_id = turn_id
        self.span_text = span_text
        super().__init__(f"turn '{turn_id}': amount span {span_text!r} could not be disambiguated")


__all__ = [
    "AmountClarificationRequired",
    "ModelResponseMalformed",
    "VoiceAgentError",
]
