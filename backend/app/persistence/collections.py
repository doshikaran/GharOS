"""Firestore collection layout — `docs/adr/001-firestore-edge-layout.md`.

One top-level collection per node type, plus one flat top-level `edges`
collection. This module is the single source of truth mapping each
`contracts.graph_types` node class to its collection name, so nothing else
in `app.persistence` / `app.graph` hardcodes a collection-name string.
"""

from __future__ import annotations

from contracts.graph_types import (
    ActionRecord,
    ApprovalRequest,
    AttendanceRecord,
    Branch,
    Constraint,
    CouncilPosition,
    Decision,
    LedgerEvent,
    Obligation,
    Outcome,
    Pattern,
    Person,
    Provider,
    PurchaseItem,
    RecurringCommitment,
    SourceDocument,
    ValuationProfile,
    Vendor,
)

EDGES_COLLECTION = "edges"
"""ADR-001: one flat top-level collection for every edge, regardless of
type — never subcollections under a node's own document."""

NODE_INDEX_COLLECTION = "node_index"
"""Firestore is document-shaped: `get_node(node_id)` (spec §5.7,
`contracts.repositories.GraphReader.get_node`) takes an id with no type
hint, but ADR-001 mandates per-type node collections. This collection is
the type-lookup index (`{node_id: {"collection": <name>}}`) that makes
type-agnostic id resolution an O(1) point read instead of a 16-collection
fan-out scan. Maintained transactionally alongside every node write —
never a source of truth on its own, always derived."""

VERSIONS_SUBCOLLECTION = "versions"
"""Per-node immutable version log (`{collection}/{node_id}/versions/{n}`).
The top-level `{collection}/{node_id}` document is a fast-read cache of the
*current* version only; the versions subcollection is the append-only
source of truth for history (PHASES.md Phase 1 work item 3 — writes create
versions, the prior version is never deleted or overwritten in place)."""

NODE_TYPE_TO_COLLECTION: dict[type, str] = {
    Person: "persons",
    Constraint: "constraints",
    Obligation: "obligations",
    LedgerEvent: "ledger_events",
    RecurringCommitment: "recurring_commitments",
    Vendor: "vendors",
    Provider: "providers",
    Decision: "decisions",
    Branch: "branches",
    CouncilPosition: "council_positions",
    Outcome: "outcomes",
    SourceDocument: "source_documents",
    ActionRecord: "action_records",
    ApprovalRequest: "approval_requests",
    PurchaseItem: "purchase_items",
    Pattern: "patterns",
    AttendanceRecord: "attendance_records",
    ValuationProfile: "valuation_profiles",
}
"""spec §5.2 — all 18 node types (`contracts.graph_types`). Adding a node
type is a CTO-only contract change (`contracts/graph_types.py`); this
table must be extended in lockstep, and `test_serialization.py` fails loudly
if it ever isn't (asserts this dict's key set matches the contract's node
dataclasses)."""

COLLECTION_TO_NODE_TYPE: dict[str, type] = {v: k for k, v in NODE_TYPE_TO_COLLECTION.items()}


def collection_for(node_type: type) -> str:
    """Returns the Firestore collection name for a node class.

    Raises:
        KeyError: `node_type` is not one of the 17 registered node types.
    """
    return NODE_TYPE_TO_COLLECTION[node_type]


def node_type_for_collection(collection: str) -> type:
    """Reverse lookup: collection name -> node dataclass.

    Raises:
        KeyError: `collection` is not a registered node collection.
    """
    return COLLECTION_TO_NODE_TYPE[collection]
