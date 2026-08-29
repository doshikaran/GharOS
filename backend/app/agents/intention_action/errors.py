"""Typed errors for `backend/app/agents/intention_action/` (A22-A26, spec
§9, PHASES.md Phase 9).

Mirrors `app.agents.ledger.errors`/`app.agents.fair_allocator.errors`'s
role for their own packages deliberately as a separate module, not a
shared import, so this package's error taxonomy stays self-contained (the
same per-package boundary `reasoning.errors`/`app.agents.errors`/
`app.agents.consequence.errors`/`app.agents.ledger.errors`/
`app.agents.fair_allocator.errors` already establish).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId, NodeId


class IntentionActionAgentError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/intention_action/`. Mirrors the role
    `app.agents.ledger.errors.LedgerAgentError` /
    `app.agents.fair_allocator.errors.FairAllocatorAgentError` play for
    their own packages."""


class ModelResponseMalformed(IntentionActionAgentError):
    """Raised when an LLM-backed Intention->Action agent's (A22/A23/A24/
    A25/A26) response cannot be parsed into the exact JSON shape its
    prompt demands, or names something outside what it was actually given
    (an unknown blocker type, a modality identical to the one being
    avoided, a delegate not among the real eligible candidates). A
    malformed response is never silently reinterpreted as an empty or
    best-guess result (safety invariant #7's analogue here) — the caller
    must retry, escalate, or fail the invocation, but never fabricate a
    plausible-looking diagnosis, fact, narrowing, or escalation option
    from unparseable or out-of-bounds model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


class NoMatchingFrictionPattern(IntentionActionAgentError):
    """Raised by `friction_profile.increment_existing_pattern` if called
    directly against a person with no existing `Pattern` of the given
    `BlockerType` on file — callers should use
    `friction_profile.apply_diagnosis_correction`, which creates a new
    `Pattern` in exactly this situation instead of raising; this error
    exists for the narrower internal helper so a genuine "expected an
    existing pattern but found none" bug does not silently create a
    duplicate."""

    def __init__(self, *, person_id: NodeId, blocker_type: str) -> None:
        self.person_id = person_id
        self.blocker_type = blocker_type
        super().__init__(f"no existing '{blocker_type}' friction pattern characterizes person {person_id!r}")


__all__ = ["IntentionActionAgentError", "ModelResponseMalformed", "NoMatchingFrictionPattern"]
