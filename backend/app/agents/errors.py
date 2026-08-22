"""Typed errors for `backend/app/agents/` — the ADK agent layer.

Distinct from `backend/app/reasoning/errors.py`: reasoning errors cover
resolving/calling a model client (tier routing, the Pro-tier allowlist, a
raw Vertex AI call failing). Agent errors cover an ADK agent's *run* not
completing the way its design requires — e.g. a required tool call never
happened, or no final response was produced — a different failure surface
even when the proximate cause is the same underlying model call.

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
Per safety invariant #7: a failed or incomplete agent run is never
reinterpreted as success.
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class AgentError(Exception):
    """Base class for every typed error raised by `backend/app/agents/`.

    Mirrors the role `reasoning.errors.ReasoningError` plays for the
    reasoning layer and `contracts.errors.GharOSError` plays for the graph
    and action layers, scoped to code E2 owns.
    """


class AgentRunIncomplete(AgentError):
    """Raised when an ADK agent run finishes without producing the tool
    call and/or final response its design requires.

    This is the agent-layer analogue of `reasoning.errors.GeminiCallFailed`
    for the ADK agent/tool loop specifically: an ADK run that does not
    demonstrably invoke its required tool, or produces no final text
    response, is a failure — never silently reported as a successful
    demo or agent invocation (safety invariant #7).
    """

    def __init__(self, *, agent_id: AgentId, reason: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        super().__init__(f"agent '{agent_id}' run did not complete as designed: {reason}")
