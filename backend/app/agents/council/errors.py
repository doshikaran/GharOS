"""Typed errors for `backend/app/agents/council/` (A41-A49, spec §12,
§15.9, PHASES.md Phase 12, ADR-019).

Mirrors `app.agents.simulator.errors`'s role for its own package
deliberately as a separate module, not a shared import, so this package's
error taxonomy stays self-contained (the established per-package boundary
convention).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId, NodeId


class CouncilError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/council/`. Mirrors
    `app.agents.simulator.errors.SimulatorError`'s role for its own
    package."""


class ModelResponseMalformed(CouncilError):
    """Raised when an LLM-backed Council agent's response cannot be parsed
    into the exact JSON shape its prompt demands, or names something
    outside what it was actually given — e.g. a specialist "eliminating" a
    branch id the caller never proposed, or a delegate scoring a branch id
    that is not in its own request. A malformed response is never silently
    reinterpreted as an empty or best-guess result (safety invariant #7's
    analogue here) — the caller must retry, escalate, or fail the
    invocation, but never fabricate a plausible-looking result from
    unparseable or out-of-bounds model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


class NoSurvivingBranches(CouncilError):
    """Raised by the pipeline when every candidate branch was eliminated by
    a HARD constraint before delegate scoring could even begin — a real,
    expected failure mode (spec §12.3 Phase 2: hard constraints "remove
    options rather than being weighed"), never silently resolved by
    picking an eliminated option or fabricating a new one. The caller must
    escalate to the household, exactly as any other R4 dead end would."""

    def __init__(self, *, decision_id: NodeId, eliminated_branch_ids: tuple[NodeId, ...]) -> None:
        self.decision_id = decision_id
        self.eliminated_branch_ids = eliminated_branch_ids
        super().__init__(
            f"decision '{decision_id}': every candidate branch was eliminated "
            f"({eliminated_branch_ids}) — nothing survives for delegate scoring"
        )


class MissingParticipantWiring(CouncilError):
    """Raised by `pipeline.run` when A41's `CouncilComposition` names a
    specialist id or delegate person id that the caller's own
    `pipeline.CouncilParticipants` never wired a real agent instance for —
    a real caller-side wiring bug, never silently skipped (silently
    skipping would under-convene the Council relative to what A41 itself
    decided, and would make `report()`/`score()` calls happen for a subset
    of participants without anyone noticing)."""

    def __init__(self, *, kind: str, key: str) -> None:
        self.kind = kind
        self.key = key
        super().__init__(f"convener named {kind} {key!r} but no participant was wired for it")


__all__ = [
    "CouncilError",
    "MissingParticipantWiring",
    "ModelResponseMalformed",
    "NoSurvivingBranches",
]
