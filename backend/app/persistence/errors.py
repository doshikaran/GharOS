"""Typed errors for `backend/app/persistence/`'s raw-payload storage and
region-reference resolution (PHASES.md Phase 3 work item: "source-document
storage with region references").

`contracts/errors.py` is frozen and CTO-only — it defines the graph- and
action-layer error taxonomy that every subsystem shares. A raw payload ref
that fails to resolve, or a `SourceRef.region` string that is malformed,
are failure modes local to this package's own storage abstraction, not the
graph/action layer, so they live here instead (mirrors the precedent set
by `app.reasoning.errors.ReasoningError` and `app.audit.errors`).

Per gharos-standards rule 7: no bare `except:`, no swallowed exceptions —
every expected failure path in `raw_payload_store.py` / `region_resolver.py`
raises one of these, never a generic `Exception`, and a missing payload is
never silently reinterpreted as empty bytes (safety invariant #7's
"a failed tool call never produces a fabricated success" applies equally
here: a failed *retrieval* must never produce fabricated bytes).
"""

from __future__ import annotations


class PersistenceError(Exception):
    """Base class for every typed error raised by `backend/app/persistence/`.

    Mirrors the role `contracts.errors.GharOSError` plays for the graph
    and action layers, scoped to code E1 owns in this package.
    """


class RawPayloadNotFound(PersistenceError):
    """Raised by `RawPayloadStore.retrieve` (and `content_type_of`) when
    `raw_payload_ref` does not resolve to any stored payload — either
    because it was never stored, or because it is not a well-formed ref
    for the concrete store's addressing scheme. Never returns empty or
    garbage bytes in this case; always raises."""

    def __init__(self, *, raw_payload_ref: str) -> None:
        self.raw_payload_ref = raw_payload_ref
        super().__init__(f"raw payload ref {raw_payload_ref!r} does not resolve to any stored payload")


class SourceDocumentNotFound(PersistenceError):
    """Raised by `region_resolver.resolve_source_ref` when
    `SourceRef.source_document_id` does not resolve to a current
    `contracts.graph_types.SourceDocument` node via the injected
    `GraphReader`."""

    def __init__(self, *, source_document_id: str) -> None:
        self.source_document_id = source_document_id
        super().__init__(f"no SOURCE_DOCUMENT node found for id {source_document_id!r}")


class MalformedRegion(PersistenceError):
    """Raised when a `SourceRef.region` string matches neither
    region-locator convention this codebase supports (see
    `region_resolver.py`'s module docstring for the two documented
    conventions). Every extraction agent from Phase 3's E2 side onward
    must produce regions this can parse."""

    def __init__(self, *, region: str, reason: str) -> None:
        self.region = region
        self.reason = reason
        super().__init__(f"malformed region locator {region!r}: {reason}")


class RegionOutOfBounds(PersistenceError):
    """Raised when a `SourceRef.region` string is syntactically
    well-formed for a supported convention but is not resolvable against
    the *actual* retrieved payload (e.g. a byte-offset span whose `end`
    exceeds the payload's real length)."""

    def __init__(self, *, region: str, detail: str) -> None:
        self.region = region
        self.detail = detail
        super().__init__(f"region locator {region!r} out of bounds: {detail}")
