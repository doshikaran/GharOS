"""Typed errors for `backend/app/graph/`'s HTTP-facing, non-Protocol graph
queries (PHASES.md Phase 6: streaming/subscription endpoint, path query
API).

`contracts/errors.py` is frozen and CTO-only — it defines the graph- and
action-layer error taxonomy every subsystem shares. "No node exists at this
id" is a failure local to this package's own concrete query surface (the
`GraphReader` Protocol's `get_node` already returns `None` for exactly this
case; this class exists for callers — `JustificationExplainer`,
`app.api.graph_router` — that need to turn that `None` into a clear,
typed failure rather than silently walking from a nonexistent root).
Mirrors the local-error convention `app.persistence.errors` already
established (`SourceDocumentNotFound`, `RawPayloadNotFound`, etc.).
"""

from __future__ import annotations


class GraphQueryError(Exception):
    """Base class for every typed error raised by `backend/app/graph/`'s
    concrete, non-Protocol query surface."""


class NodeNotFound(GraphQueryError):
    """Raised when a requested `node_id` does not resolve to any current
    node. The HTTP layer (`app.api.graph_router`) turns this into a 404 —
    a malformed/unresolvable node id is a caller error, never a 500."""

    def __init__(self, *, node_id: str) -> None:
        self.node_id = node_id
        super().__init__(f"no node found for id {node_id!r}")
