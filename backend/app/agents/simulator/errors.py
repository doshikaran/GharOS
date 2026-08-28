"""Typed errors for `backend/app/agents/simulator/` (A35-A40, spec §11,
§15.8, PHASES.md Phase 11, ADR-017).

Mirrors `app.agents.concierge.errors`/`app.agents.intention_action.errors`'s
role for their own packages deliberately as a separate module, not a
shared import, so this package's error taxonomy stays self-contained (the
established per-package boundary convention).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId, NodeId


class SimulatorError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/simulator/`. Mirrors the role
    `app.agents.concierge.errors.ConciergeError` plays for its own
    package."""


class ModelResponseMalformed(SimulatorError):
    """Raised when an LLM-backed Simulator agent's response cannot be
    parsed into the exact JSON shape its prompt demands, or names
    something outside what it was actually given — e.g. a branch label
    the caller never proposed, an unconsidered-option that merely restates
    a proposed branch, or a blank claim/critique field. A malformed
    response is never silently reinterpreted as an empty or best-guess
    result (safety invariant #7's analogue here) — the caller must retry,
    escalate, or fail the invocation, but never fabricate a plausible-
    looking result from unparseable or out-of-bounds model output.
    """

    def __init__(self, *, agent_id: AgentId, reason: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.reason = reason
        self.raw_text = raw_text
        super().__init__(f"agent '{agent_id}' produced an unparseable response: {reason}")


class VerdictLeaked(SimulatorError):
    """Raised when A40 Decision Synthesizer's own output text (trade-offs,
    branch summaries, open questions, or a follow-up answer) contains
    verdict-shaped language on an emotionally-loaded family decision —
    spec §15.8 A40's explicit forbidden behaviour, and `DecisionBrief`'s
    own structural absence of any recommendation field (see
    `types.DecisionBrief`'s docstring). `DecisionBrief` having no such
    *field* is the primary, structural guarantee; this exception is a
    second, defence-in-depth check against a model smuggling verdict-
    shaped *prose* into a field that does exist (e.g. `trade_offs`
    containing "we recommend Option B"). Never silently stripped or
    rewritten — the whole response is rejected, exactly like
    `ModelResponseMalformed`.
    """

    def __init__(self, *, agent_id: AgentId, field: str, matched_phrase: str, raw_text: str) -> None:
        self.agent_id = agent_id
        self.field = field
        self.matched_phrase = matched_phrase
        self.raw_text = raw_text
        super().__init__(
            f"agent '{agent_id}' output field '{field}' contains verdict-shaped language "
            f"({matched_phrase!r}) on what must remain a trade-off presentation, never a verdict"
        )


class BranchNotFound(SimulatorError):
    """Raised when A38 Consistency Critic is asked to critique a
    `branch_id` that does not currently resolve to a real `Branch` node
    (never found at all, or superseded/absent) — A38 must read the real
    current `Branch` before it can honestly append to its `critiques`
    tuple (see `types.CritiqueRequest`'s own docstring: the caller
    supplies a `BranchProjection`, but only the graph's own current
    version carries `decision_id` and the existing `critiques` history to
    append onto). A caller passing a stale or fabricated id is a real,
    expected failure mode — never silently treated as "no critique
    needed."""

    def __init__(self, *, agent_id: AgentId, branch_id: NodeId) -> None:
        self.agent_id = agent_id
        self.branch_id = branch_id
        super().__init__(f"agent '{agent_id}' could not find a current Branch node for '{branch_id}'")


__all__ = ["BranchNotFound", "ModelResponseMalformed", "SimulatorError", "VerdictLeaked"]
