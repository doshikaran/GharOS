"""Shared node/edge -> wire-JSON envelope builders for Phase 6's
HTTP-facing graph endpoints (`app.api.graph_router`'s `/graph/snapshot`,
`/graph/stream`, and `/graph/nodes/{id}/justification`) and the live
`app.graph.change_stream.FirestoreGraphChangeStream` broadcaster — one
shared implementation so a node/edge looks identical whether it arrived
via a full snapshot or a live push.

**Deliberately built from raw, undecoded Firestore documents**
(`FirestoreGraphStore.all_current_node_documents` / `all_edge_documents`,
and the raw `dict` a Firestore `on_snapshot` callback's `DocumentChange`
hands back) rather than round-tripping through `app.persistence.codecs`'
typed decoders and back — the wire shape below is exactly the shape a raw
document already has, once its `Provenance` map is unpacked and every
datetime is stringified. Every per-node-type field lands under `"fields"`
untouched (JSON-safety aside): this module has no per-node-type
`decode_*` knowledge beyond the one dispatch table below for the
human-readable `label` — it never needs field-shape knowledge from
`contracts.graph_types` beyond the 16 classes' `id`/`type` identity.

**Node-type tag convention (frozen for this phase — the frontend's
TypeScript node-type union is built against this exact naming):** every
node's `"type"` field is the node's `contracts.graph_types` class name
converted to upper snake case — `Person` -> `"PERSON"`,
`LedgerEvent` -> `"LEDGER_EVENT"`, `RecurringCommitment` ->
`"RECURRING_COMMITMENT"`, `CouncilPosition` -> `"COUNCIL_POSITION"`,
`SourceDocument` -> `"SOURCE_DOCUMENT"`, `ActionRecord` ->
`"ACTION_RECORD"`, `ApprovalRequest` -> `"APPROVAL_REQUEST"`,
`PurchaseItem` -> `"PURCHASE_ITEM"` — spelled out explicitly in
`NODE_TYPE_TAGS` below (one literal string per type) rather than derived
by a runtime regex, so the exact wire string is grep-able in one place.
Edge `"type"` is, by contrast, simply `EdgeType.value` as already defined
in `contracts.graph_types` (already lower-snake, e.g. `"implies"`,
`"conflicts_with"`) — no separate convention needed there.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from contracts.graph_types import (
    ActionRecord,
    ApprovalRequest,
    AttendanceRecord,
    Branch,
    Constraint,
    CouncilPosition,
    Decision,
    EdgeType,
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

_LABEL_TRUNCATE_LIMIT = 60
"""Applied to OUTCOME.predicted and PATTERN.description per this phase's
frozen wire contract ("truncate to ~60 chars with an ellipsis")."""

# ---------------------------------------------------------------------------
# Node-type tags (see module docstring — the frozen wire convention)
# ---------------------------------------------------------------------------

NODE_TYPE_TAGS: dict[type, str] = {
    Person: "PERSON",
    Constraint: "CONSTRAINT",
    Obligation: "OBLIGATION",
    LedgerEvent: "LEDGER_EVENT",
    RecurringCommitment: "RECURRING_COMMITMENT",
    Vendor: "VENDOR",
    Provider: "PROVIDER",
    Decision: "DECISION",
    Branch: "BRANCH",
    CouncilPosition: "COUNCIL_POSITION",
    Outcome: "OUTCOME",
    SourceDocument: "SOURCE_DOCUMENT",
    ActionRecord: "ACTION_RECORD",
    ApprovalRequest: "APPROVAL_REQUEST",
    PurchaseItem: "PURCHASE_ITEM",
    Pattern: "PATTERN",
    AttendanceRecord: "ATTENDANCE_RECORD",
    ValuationProfile: "VALUATION_PROFILE",
}
"""One entry per node type in `contracts.graph_types` (spec §5.2) — must
have the same key set as `app.persistence.collections.NODE_TYPE_TO_COLLECTION`
(`test_graph_serialization.py` asserts this)."""


# ---------------------------------------------------------------------------
# node_label dispatcher (spec's per-node-type label rules, this phase)
# ---------------------------------------------------------------------------


def _truncate(text: str, *, limit: int = _LABEL_TRUNCATE_LIMIT) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _label_person(fields: dict[str, Any]) -> str:
    return str(fields["display_name"])


def _label_constraint(fields: dict[str, Any]) -> str:
    return f"{str(fields['kind']).title()} constraint"


def _label_obligation(fields: dict[str, Any]) -> str:
    return str(fields["title"])


def _label_ledger_event(fields: dict[str, Any]) -> str:
    return f"{fields['kind']} — {fields['currency']} {fields['amount']}"


def _label_recurring_commitment(fields: dict[str, Any]) -> str:
    return str(fields["label"])


def _label_vendor(fields: dict[str, Any]) -> str:
    # VENDOR has no name field on the frozen contract (a known quirk, not
    # fixed this phase) — fall back to category, with the first contact if
    # one is present, so two vendors of the same category stay visually
    # distinguishable in the graph view.
    category = str(fields["category"])
    contacts = fields.get("contacts") or []
    if contacts:
        return f"{category} ({contacts[0]})"
    return category


def _label_provider(fields: dict[str, Any]) -> str:
    return str(fields["name"])


def _label_decision(fields: dict[str, Any]) -> str:
    return str(fields["question"])


def _label_branch(fields: dict[str, Any]) -> str:
    return str(fields["label"])


def _label_council_position(fields: dict[str, Any]) -> str:
    return f"{fields['held_by_agent']} — {fields['stance']}"


def _label_outcome(fields: dict[str, Any]) -> str:
    return _truncate(str(fields["predicted"]))


def _label_source_document(fields: dict[str, Any]) -> str:
    channel = str(fields["channel"])
    document_type = fields.get("document_type")
    return f"{channel} document ({document_type})" if document_type else f"{channel} document"


def _label_action_record(fields: dict[str, Any]) -> str:
    return str(fields["action_type"])


def _label_approval_request(fields: dict[str, Any]) -> str:
    return str(fields["proposed_action_summary"])


def _label_purchase_item(fields: dict[str, Any]) -> str:
    return str(fields["description"])


def _label_pattern(fields: dict[str, Any]) -> str:
    return _truncate(str(fields["description"]))


def _label_attendance_record(fields: dict[str, Any]) -> str:
    return f"{fields['month']} attendance"


def _label_valuation_profile(fields: dict[str, Any]) -> str:
    return f"{fields['elicitation_method']} valuation"


_NODE_LABEL_DISPATCH: dict[str, Callable[[dict[str, Any]], str]] = {
    "PERSON": _label_person,
    "CONSTRAINT": _label_constraint,
    "OBLIGATION": _label_obligation,
    "LEDGER_EVENT": _label_ledger_event,
    "RECURRING_COMMITMENT": _label_recurring_commitment,
    "VENDOR": _label_vendor,
    "PROVIDER": _label_provider,
    "DECISION": _label_decision,
    "BRANCH": _label_branch,
    "COUNCIL_POSITION": _label_council_position,
    "OUTCOME": _label_outcome,
    "SOURCE_DOCUMENT": _label_source_document,
    "ACTION_RECORD": _label_action_record,
    "APPROVAL_REQUEST": _label_approval_request,
    "PURCHASE_ITEM": _label_purchase_item,
    "PATTERN": _label_pattern,
    "ATTENDANCE_RECORD": _label_attendance_record,
    "VALUATION_PROFILE": _label_valuation_profile,
}
"""Strategy-pattern registry (PHASES.md §2.2) — one label function per
node-type tag, never a growing if/elif chain. Key set must match
`NODE_TYPE_TAGS`'s value set exactly."""


def node_label(node_type_name: str, raw_fields: dict[str, Any]) -> str:
    """Builds a short, human-readable label for one node, dispatched on its
    wire-convention type tag (`NODE_TYPE_TAGS` values, e.g. `"PERSON"`).

    Args:
        node_type_name: one of `NODE_TYPE_TAGS`'s values.
        raw_fields: the node's raw (undecoded) Firestore document dict —
            every per-type field this node type's `encode_*` codec wrote,
            plus `id`/`provenance` (ignored here; only type-specific keys
            are read).

    Raises:
        ValueError: `node_type_name` is not a registered tag.
    """
    try:
        label_fn = _NODE_LABEL_DISPATCH[node_type_name]
    except KeyError as exc:
        raise ValueError(f"no label dispatcher registered for node type {node_type_name!r}") from exc
    return label_fn(raw_fields)


# ---------------------------------------------------------------------------
# JSON-safety
# ---------------------------------------------------------------------------


def json_safe(value: Any) -> Any:
    """Recursively converts a raw Firestore-document value into a
    JSON-serialisable one: datetimes (including the `DatetimeWithNanoseconds`
    subclass the client library returns) become ISO-8601 strings; dicts and
    lists/tuples recurse; everything else (str, float, int, bool, None)
    passes through unchanged."""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [json_safe(item) for item in value]
    return value


# ---------------------------------------------------------------------------
# Node / edge wire envelopes
# ---------------------------------------------------------------------------


_NON_DOMAIN_RAW_KEYS = frozenset({"id", "provenance", "_version_seq"})
"""Raw Firestore-document keys excluded from `fields`. `id`/`provenance`
are already surfaced at the envelope's top level; `_version_seq` is
`FirestoreGraphStore`'s own internal versioning bookkeeping field
(`app.persistence.firestore_store`'s module docstring: "Never part of the
domain shape in `contracts.graph_types`... never surfaced through any
repository return type either") — a raw-document consumer like this one
must exclude it explicitly, since it is not one of `contracts.graph_types`'
per-node-type fields at all."""


def build_node_envelope(node_type: type, doc_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Builds one `/graph/snapshot`-shaped node JSON object from a raw
    (undecoded) Firestore node document.

    `derivation`/`confidence`/`source_document_id`/`region` come from the
    node's `provenance` map; `source_document_id`/`region` are `None` when
    `provenance.source_ref` is `None` (legitimate for AMBIGUOUS derivation
    with no single source — spec §5.6). Every other stored field lands
    under `fields`, JSON-safe, with `_NON_DOMAIN_RAW_KEYS` excluded.
    """
    tag = NODE_TYPE_TAGS[node_type]
    provenance = raw.get("provenance") or {}
    source_ref = provenance.get("source_ref")
    fields = {key: json_safe(value) for key, value in raw.items() if key not in _NON_DOMAIN_RAW_KEYS}
    return {
        "id": doc_id,
        "type": tag,
        "label": node_label(tag, raw),
        "derivation": provenance.get("derivation"),
        "confidence": provenance.get("confidence"),
        "source_document_id": source_ref.get("source_document_id") if source_ref else None,
        "region": source_ref.get("region") if source_ref else None,
        "created_at": json_safe(provenance.get("created_at")),
        "fields": fields,
    }


CONFLICT_EDGE_TYPE_VALUES: frozenset[str] = frozenset(
    {EdgeType.CONFLICTS_WITH.value, EdgeType.VIOLATES.value, EdgeType.CONTRADICTS.value}
)
"""The literal, named, documented set backing `is_conflict` — exactly
CONFLICTS_WITH / VIOLATES / CONTRADICTS, never inferred by string-matching
"conflict" in an edge-type name (this phase's frozen wire contract)."""


def build_edge_envelope(doc_id: str, raw: dict[str, Any]) -> dict[str, Any]:
    """Builds one `/graph/snapshot`-shaped edge JSON object from a raw
    (undecoded) Firestore edge document."""
    provenance = raw.get("provenance") or {}
    edge_type = raw.get("edge_type")
    return {
        "id": doc_id,
        "type": edge_type,
        "from_id": raw.get("from_id"),
        "to_id": raw.get("to_id"),
        "derivation": provenance.get("derivation"),
        "confidence": provenance.get("confidence"),
        "is_conflict": edge_type in CONFLICT_EDGE_TYPE_VALUES,
    }
