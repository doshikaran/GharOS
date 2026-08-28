"""Typed errors for `backend/app/agents/concierge/` (A50-A56, spec §13,
PHASES.md Phase 10).

Mirrors `app.agents.ledger.errors` / `app.agents.intention_action.errors`'s
role for their own packages deliberately as a separate module, not a
shared import, so this package's error taxonomy stays self-contained (the
same per-package boundary `reasoning.errors` / `app.arbitration.errors`
already establish).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class ConciergeError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/concierge/`. Mirrors the role
    `app.agents.ledger.errors.LedgerAgentError` plays for its own
    package."""


class ModelResponseMalformed(ConciergeError):
    """Raised when an LLM-backed Concierge agent's response cannot be
    parsed into the exact JSON shape its prompt demands, or names
    something outside what it was actually given — e.g. (A51, A54, or
    the sandbox counterparty) a malformed candidate, counterparty turn,
    or call decision; (A50, A52, A53, A55) a clarifying question
    targeting a fact the graph-first check already resolved, an urgency
    value outside the closed `{routine, elevated}` set, or a blank call
    objective. A malformed response is never silently reinterpreted as an
    empty or best-guess result (safety invariant #7's analogue here) —
    the caller must retry, escalate, or fail the invocation, but never
    fabricate a plausible-looking result from unparseable or
    out-of-bounds model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


__all__ = ["ConciergeError", "ModelResponseMalformed"]
