"""Typed errors for `backend/app/agents/intake/` — the Phase 3 intake-layer
agents (A2-A6) and the fourteen `ExtractionStrategy` implementations.

Mirrors the role `app.reasoning.errors.ReasoningError` and
`app.agents.errors.AgentError` play for their own layers (gharos-standards
rule 7: no bare `except:`, no swallowed exceptions — every expected
failure path here raises one of these, never a generic `Exception`).
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class IntakeAgentError(Exception):
    """Base class for every typed error raised by `backend/app/agents/intake/`."""


class ModelResponseMalformed(IntakeAgentError):
    """Raised when an LLM-backed intake agent's response cannot be parsed
    into the exact JSON shape its prompt demands.

    A malformed response is never silently reinterpreted as an empty or
    best-guess result (safety invariant #7's ingestion-layer analogue) —
    the caller must retry, escalate, or fail the invocation, but never
    fabricate a plausible-looking result from unparseable model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")
