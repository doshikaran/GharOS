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


class ConsequenceEngineError(Exception):
    """Base class for every typed error raised by
    `backend/app/agents/consequence/`. Mirrors the role
    `contracts.errors.GharOSError` plays for the graph/action layers and
    `reasoning.errors.ReasoningError` plays for the reasoning layer,
    scoped to this package."""


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


__all__ = ["ConsequenceEngineError", "SourceDocumentNotResolvable"]
