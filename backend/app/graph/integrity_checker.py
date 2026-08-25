"""`FirestoreGraphIntegrityChecker` — the real, Firestore-backed
`contracts.repositories.GraphIntegrityChecker` (spec §16.2): orphans,
missing provenance, dangling edges. Deterministic tool, never an LLM.

Every check here operates on *raw, undecoded* Firestore documents
(`FirestoreGraphStore.all_current_node_documents` / `all_edge_documents` /
`node_exists`) rather than typed nodes — finding and reporting a
structurally corrupted document (e.g. `provenance: None`) is this class's
entire job, so it must never itself crash decoding one into a typed
dataclass before it gets the chance to report it.

Must be clean (zero violations, other than expected `absent_from`
signals — see below) on seeded demo data at every gate from Phase 1
onward (E1 charter).
"""

from __future__ import annotations

from typing import Any

from contracts.errors import ProvenanceMissing
from contracts.graph_types import ApprovalRequest, EdgeType, NodeId

from app.persistence.firestore_store import FirestoreGraphStore
from app.persistence.provenance_guard import subject_from_raw_document, validate_provenance

_NEVER_EDGE_CONNECTED_NODE_TYPE_NAMES = (ApprovalRequest.__name__,)
"""**Narrowed in Phase 5 (ADR-012, DEBT-002's repayment).** Originally both
ACTION_RECORD and APPROVAL_REQUEST were special-cased here, since the
frozen `EdgeType` enum had no member naming either as an endpoint at all —
every correctly-written node of either type was unconditionally an
edge-orphan under the old contract. Phase 5 added `ACTS_ON`, `AUTHORIZES`,
and `APPROVED_BY` (ADR-012) and `app.arbitration.approval_gate.
ApprovalGate.approve_and_execute` now writes all three for real, atomically
alongside every `ActionRecord` it creates — an ActionRecord is therefore
now *always* edge-connected (one outgoing `ACTS_ON`, one incoming
`AUTHORIZES`) by construction, and is removed from this list.

APPROVAL_REQUEST stays special-cased, but for a different, narrower, and
entirely expected reason now: `ApprovalGate.request_approval` deliberately
writes a `PENDING` request with zero edges (nothing has been authorized
yet), and `AUTHORIZES`/`APPROVED_BY` are only ever added on the successful
tail of `approve_and_execute`. A `PENDING`, `REJECTED`, or `EXPIRED`
request — or an `APPROVED` one whose underlying tool invocation then
failed (see that method's own docstring: audit and status update happen
before execution is attempted, so a tool failure still leaves a resolved,
edge-orphaned request) — is legitimately, permanently edge-orphaned by
design, not corruption. This is normal lifecycle state, not deferred debt;
it is not expected to ever be narrowed further to a status-conditional
check, since "resolved but never executed anything real" is a genuine,
common, correct end state for a request (e.g. every REJECTED request ever
written). Compared by type *name* rather than `isinstance` because this
check works over raw `(node_type, doc_id, raw_dict)` triples, where
`node_type` is already the class object from the collection registry."""


class FirestoreGraphIntegrityChecker:
    """Structurally satisfies `contracts.repositories.GraphIntegrityChecker`."""

    def __init__(self, store: FirestoreGraphStore) -> None:
        self._store = store

    def check(self, scope: str) -> tuple[str, ...]:
        """`scope` is accepted for signature conformance; Phase 1 always
        checks the whole store (integrity is a whole-graph property — a
        dangling edge outside a narrow "scope" is still corruption).
        Returns human-readable violations, empty tuple if clean."""
        del scope
        nodes = self._store.all_current_node_documents()
        edges = self._store.all_edge_documents()
        violations: list[str] = []
        violations.extend(self._provenance_violations(nodes, edges))
        violations.extend(self._dangling_edge_violations(edges))
        violations.extend(self._orphan_node_violations(nodes, edges))
        return tuple(violations)

    def _provenance_violations(
        self,
        nodes: tuple[tuple[type, str, dict[str, Any] | None], ...],
        edges: tuple[tuple[str, dict[str, Any] | None], ...],
    ) -> list[str]:
        violations: list[str] = []
        for _node_type, doc_id, raw in nodes:
            try:
                validate_provenance(subject_from_raw_document(doc_id, raw))
            except ProvenanceMissing as exc:
                violations.append(f"node {doc_id}: missing provenance fields {exc.missing_fields}")
        for edge_id, raw in edges:
            try:
                validate_provenance(subject_from_raw_document(edge_id, raw))
            except ProvenanceMissing as exc:
                violations.append(f"edge {edge_id}: missing provenance fields {exc.missing_fields}")
        return violations

    def _dangling_edge_violations(self, edges: tuple[tuple[str, dict[str, Any] | None], ...]) -> list[str]:
        violations: list[str] = []
        for edge_id, raw in edges:
            if raw is None:
                continue  # already reported as a provenance/corruption violation
            from_id = raw.get("from_id")
            to_id = raw.get("to_id")
            edge_type = raw.get("edge_type")
            if from_id is not None and not self._store.node_exists(NodeId(from_id)):
                violations.append(f"edge {edge_id}: from_id {from_id} does not resolve to a live node")
            if edge_type == EdgeType.ABSENT_FROM.value:
                # absent_from's to_id is *expected to not resolve* — a
                # SOURCE_DOCUMENT that never arrived is the whole point of
                # this edge type (spec §5.5): it is a first-class signal,
                # not corruption. Only its from_id must resolve.
                continue
            if to_id is not None and not self._store.node_exists(NodeId(to_id)):
                violations.append(f"edge {edge_id}: to_id {to_id} does not resolve to a live node")
        return violations

    def _orphan_node_violations(
        self,
        nodes: tuple[tuple[type, str, dict[str, Any] | None], ...],
        edges: tuple[tuple[str, dict[str, Any] | None], ...],
    ) -> list[str]:
        touched: set[str] = set()
        for _edge_id, raw in edges:
            if raw is None:
                continue
            from_id = raw.get("from_id")
            to_id = raw.get("to_id")
            if from_id is not None:
                touched.add(str(from_id))
            if to_id is not None:
                touched.add(str(to_id))
        return [
            f"node {doc_id}: no incident edges (orphan)"
            for node_type, doc_id, _raw in nodes
            if doc_id not in touched and node_type.__name__ not in _NEVER_EDGE_CONNECTED_NODE_TYPE_NAMES
        ]
