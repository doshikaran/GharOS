"""Typed errors for `backend/app/agents/ledger/` (A28-A30, A32, A34, spec
§10, PHASES.md Phase 7).

Mirrors `app.agents.consequence.errors`'s role for its own package
deliberately as a separate module, not a shared import, so this package's
error taxonomy stays self-contained (the same per-package boundary
`reasoning.errors`/`app.agents.errors`/`app.agents.consequence.errors`
already establish).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class LedgerAgentError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/ledger/`. Mirrors the role
    `app.agents.consequence.errors.ConsequenceEngineError` plays for its
    own package."""


class ModelResponseMalformed(LedgerAgentError):
    """Raised when an LLM-backed Ledger agent's (A28/A29/A30/A32/A34)
    response cannot be parsed into the exact JSON shape its prompt
    demands. A malformed response is never silently reinterpreted as an
    empty or best-guess result (safety invariant #7's analogue here) — the
    caller must retry, escalate, or fail the invocation, but never
    fabricate a plausible-looking finding, draft, presentation, or payroll
    result from unparseable model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


class CurrencyMismatch(LedgerAgentError):
    """Raised when two figures a Ledger agent is asked to compare (e.g.
    A32's two `ConflictingFigure`s, A28's SMS-vs-ledger mismatch check)
    are denominated in different currencies — comparing raw amounts across
    currencies without conversion would silently fabricate a discrepancy
    figure that means nothing; this module refuses rather than guessing an
    exchange rate."""

    def __init__(self, *, currency_a: str, currency_b: str, context: str) -> None:
        self.currency_a = currency_a
        self.currency_b = currency_b
        self.context = context
        super().__init__(f"currency mismatch in {context}: {currency_a!r} vs {currency_b!r}")


__all__ = ["CurrencyMismatch", "LedgerAgentError", "ModelResponseMalformed"]
