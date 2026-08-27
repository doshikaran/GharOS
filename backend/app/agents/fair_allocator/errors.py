"""Typed errors for `backend/app/agents/fair_allocator/` (A17-A21, spec
§8, PHASES.md Phase 8).

Mirrors `app.agents.ledger.errors`'s role for its own package deliberately
as a separate module, not a shared import, so this package's error
taxonomy stays self-contained (the same per-package boundary
`reasoning.errors`/`app.agents.errors`/`app.agents.consequence.errors`/
`app.agents.ledger.errors` already establish).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId, NodeId


class FairAllocatorAgentError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/fair_allocator/`. Mirrors the role
    `app.agents.ledger.errors.LedgerAgentError` plays for its own
    package."""


class ModelResponseMalformed(FairAllocatorAgentError):
    """Raised when an LLM-backed Fair Allocator agent's (A17/A18/A19/A20/
    A21) response cannot be parsed into the exact JSON shape its prompt
    demands. A malformed response is never silently reinterpreted as an
    empty or best-guess result (safety invariant #7's analogue here) — the
    caller must retry, escalate, or fail the invocation, but never
    fabricate a plausible-looking preference, cost, explanation, or
    trigger from unparseable model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


class ConcessionCostDataMissing(FairAllocatorAgentError):
    """Raised by A20's `detect_concession` when `current_costs_for_person`
    has no priced entry for some task in either the prior or the new
    bundle — comparing bundle costs with a missing entry would silently
    treat an unpriced task as costing nothing, which would fabricate the
    comparison exactly as a placeholder `0.0` valuation would (spec §15.8
    A18's "never fabricate values" rule, extended here to the concession
    check that consumes those same valuations)."""

    def __init__(self, *, person_id: NodeId, missing_task_id: NodeId) -> None:
        self.person_id = person_id
        self.missing_task_id = missing_task_id
        super().__init__(
            f"cannot check for a concession by {person_id!r}: no priced cost for task "
            f"{missing_task_id!r} in their current valuation"
        )


__all__ = ["ConcessionCostDataMissing", "FairAllocatorAgentError", "ModelResponseMalformed"]
