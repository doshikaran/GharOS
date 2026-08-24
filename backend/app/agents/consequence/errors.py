"""Typed errors for `backend/app/agents/consequence/` (A12-A16, spec §7).

`contracts/errors.py` is frozen and CTO-owned — `EscalationRequired` and
`ConstraintViolation` from there are reused directly where they apply
(A13's hard-constraint-ambiguity escalation is exactly the case
`EscalationRequired`'s own docstring names as its motivating example).
The errors below cover failure modes specific to this package that do not
fit the frozen taxonomy.

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions.
"""

from __future__ import annotations

from contracts.graph_types import AgentId


class ConsequenceEngineError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/consequence/`. Mirrors the role
    `contracts.errors.GharOSError` plays for the graph/action layers and
    `reasoning.errors.ReasoningError` plays for the reasoning layer,
    scoped to this package."""


class ModelResponseMalformed(ConsequenceEngineError):
    """Raised when an LLM-backed Consequence Engine agent's (A12/A13/A14/
    A16) response cannot be parsed into the exact JSON shape its prompt
    demands. Mirrors `app.agents.intake.errors.ModelResponseMalformed`'s
    role for this package — deliberately a separate class, not a shared
    import, so each package's error taxonomy stays self-contained (the
    same pattern `reasoning.errors.ReasoningError` and
    `app.agents.errors.AgentError` already establish for their own
    layers).

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


class SourceDocumentNotResolvable(ConsequenceEngineError):
    """Raised by `context.assemble_implication_request` when the given
    `source_document_id` does not resolve to a current, text-shaped
    `contracts.graph_types.SourceDocument` — either the node does not
    exist, or its raw payload is not UTF-8 text (image/PDF-shaped
    documents are out of A12's Phase 4 scope; see that module's
    docstring)."""

    def __init__(self, *, source_document_id: str, reason: str) -> None:
        self.source_document_id = source_document_id
        self.reason = reason
        super().__init__(f"SOURCE_DOCUMENT {source_document_id!r} not resolvable for implication: {reason}")


class CandidateDependencyCycle(ConsequenceEngineError):
    """Raised by `obligation_writer.ObligationWriter.write` when a batch
    of `ImpliedObligationCandidate`s' `depends_on_candidate_ids` forms a
    cycle within the same batch — a malformed A12 output (A12's own prompt
    forbids a candidate depending on itself transitively), never silently
    written in some arbitrary partial order. A15 needs a genuine
    topological order to write dependency prerequisites before their
    dependents (so `contracts.repositories.GraphReader.dependency_chain`
    can resolve real, already-written prerequisite nodes when computing
    `must_start_by` for a later candidate in the same batch) — a cycle
    means no such order exists."""

    def __init__(self, *, candidate_ids_in_cycle: tuple[str, ...]) -> None:
        self.candidate_ids_in_cycle = candidate_ids_in_cycle
        super().__init__(
            f"candidate dependency cycle detected among: {candidate_ids_in_cycle} — "
            "cannot compute a write order"
        )


__all__ = [
    "CandidateDependencyCycle",
    "ConsequenceEngineError",
    "ModelResponseMalformed",
    "SourceDocumentNotResolvable",
]
